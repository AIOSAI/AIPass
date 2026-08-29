# =================== AIPass ====================
# Name: envcopy.py - copy-first scratch environment (Law M10)
# Description: mirrors a target into a scratch tree so the suite never runs in place
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Build the scratch environment a suite is measured in.

Law M10: *the instrument must not disturb what it measures.*  Scoring daemon in
place forges 79 log entries across 8 logs on every measurement, so nothing here
ever runs a suite against the real tree.

Two layouts:

``aipass``
    The target sits at ``<repo>/src/aipass/<name>``.  Branches import each other
    as ``aipass.<sibling>.apps...``, so the env mirrors that layout: the target
    is an rsync copy, every sibling package is a symlink to the real tree, and
    ``PYTHONPATH`` puts ``<env>/src`` ahead of the editable install's ``.pth``
    entry so ``aipass.<name>`` resolves to the copy.

``plain``
    Any other directory holding pytest targets.  Copied whole; nothing is
    symlinked.

A symlinked sibling is still writable, and a write through one really lands in
the real tree.  This is not theoretical: the first calibration run on backup put
five files into the **real** ``prax/prax_json/`` through the symlink.  So the
escape is counted and named in the artifact, and ``copy_siblings=True`` closes it
by copying every sibling instead -- slower, and the only mode in which Law M10
holds for the whole repo rather than for the target alone.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .logsetup import logger

RSYNC_EXCLUDES = ("__pycache__", ".ruff_cache", ".pytest_cache", ".git")


@dataclass
class EnvSpec:
    """Where everything landed, and how to invoke pytest inside it."""

    layout: str
    env_root: Path
    run_cwd: Path
    target_copy: Path
    target_module: str
    test_arg: str
    python: Path
    pythonpath: str
    plugin_dir: Path
    log_path: Path
    symlinked_siblings: list[str] = field(default_factory=list)
    copied_siblings: list[str] = field(default_factory=list)


class EnvError(RuntimeError):
    """The environment could not be built, or is not the one we will measure."""


def find_python(target: Path, override: str | None = None) -> Path:
    """Resolve the interpreter that owns the target's dependencies.

    Order: explicit argument, ``AUDIT_TESTS_PYTHON``, the nearest ``.venv``
    walking up from the target, then this interpreter.  No path is hardcoded --
    a checker that only runs on one machine is not a checker.

    Symlinks are deliberately NOT resolved: ``.venv/bin/python`` is a symlink to
    the system interpreter, and resolving it hands back a python that cannot see
    the venv's site-packages.  Caught here by a first run reporting
    ``No module named pytest``.
    """
    if override:
        return Path(os.path.abspath(Path(override).expanduser()))
    from_env = os.environ.get("AUDIT_TESTS_PYTHON")
    if from_env:
        return Path(os.path.abspath(Path(from_env).expanduser()))
    for parent in [target, *target.parents]:
        candidate = parent / ".venv" / "bin" / "python"
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def detect_layout(target: Path) -> tuple[str, Path | None]:
    """Return ``(layout, repo_root)``; repo_root is None for a plain target."""
    parent, grandparent = target.parent, target.parent.parent
    if parent.name == "aipass" and grandparent.name == "src":
        return "aipass", grandparent.parent
    return "plain", None


def _rsync(src: Path, dst: Path) -> None:
    """One rsync, with the excludes that keep caches and git history out."""
    dst.mkdir(parents=True, exist_ok=True)
    excludes: list[str] = []
    for name in RSYNC_EXCLUDES:
        excludes += ["--exclude", name]
    cmd = ["rsync", "-a", "--delete", *excludes, f"{src}/", f"{dst}/"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise EnvError(f"rsync of {src} failed ({result.returncode}): {result.stderr.strip()[:400]}")


def build_env(
    target: Path,
    env_root: Path,
    plugin_source: Path,
    python_override: str | None = None,
    copy_siblings: bool = False,
) -> EnvSpec:
    """Materialise the scratch env and return how to run pytest inside it."""
    target = target.resolve()
    layout, repo_root = detect_layout(target)
    env_root = env_root.resolve()
    if env_root.exists():
        shutil.rmtree(env_root)
    env_root.mkdir(parents=True)

    plugin_dir = env_root / "_audit_plugin"
    plugin_dir.mkdir()
    shutil.copy2(plugin_source, plugin_dir / plugin_source.name)
    log_path = env_root / "_audit" / "hygiene.jsonl"
    log_path.parent.mkdir()

    siblings: list[str] = []
    copied_siblings: list[str] = []
    if layout == "aipass" and repo_root is not None:
        src_dir = env_root / "src" / "aipass"
        src_dir.mkdir(parents=True)
        real_src = repo_root / "src" / "aipass"
        for name in ("__init__.py", "conftest.py"):
            if (real_src / name).is_file():
                shutil.copy2(real_src / name, src_dir / name)
        if (repo_root / "conftest.py").is_file():
            shutil.copy2(repo_root / "conftest.py", env_root / "conftest.py")
        for entry in sorted(real_src.iterdir()):
            if not entry.is_dir() or entry.name in ("__pycache__", target.name):
                continue
            if copy_siblings:
                _rsync(entry, src_dir / entry.name)
                copied_siblings.append(entry.name)
            else:
                (src_dir / entry.name).symlink_to(entry)
                siblings.append(entry.name)
        target_copy = src_dir / target.name
        _rsync(target, target_copy)
        run_cwd = env_root
        test_arg = str(Path("src") / "aipass" / target.name / "tests")
        target_module = f"aipass.{target.name}"
        pythonpath = str(env_root / "src")
    else:
        target_copy = env_root / target.name
        _rsync(target, target_copy)
        run_cwd = env_root
        test_arg = target.name
        target_module = ""
        pythonpath = str(env_root)

    if not (target_copy / "tests").is_dir():
        # Not every project puts its tests in tests/; point pytest at the copy.
        test_arg = str(target_copy.relative_to(run_cwd))

    return EnvSpec(
        layout=layout,
        env_root=env_root,
        run_cwd=run_cwd,
        target_copy=target_copy,
        target_module=target_module,
        test_arg=test_arg,
        python=find_python(target, python_override),
        pythonpath=os.pathsep.join([pythonpath, str(plugin_dir)]),
        plugin_dir=plugin_dir,
        log_path=log_path,
        symlinked_siblings=siblings,
        copied_siblings=copied_siblings,
    )


def assert_copy_is_live(spec: EnvSpec, timeout: int = 120) -> tuple[bool | None, str]:
    """Pre-flight: import the target in a child and check where it resolved.

    Harness-integrity check #3.  The editable install resolves ``aipass.*`` back
    to the real repo unless ``PYTHONPATH`` wins, and a run that measured the real
    repo is worse than no run at all.  Returns ``(verified, detail)``; verified is
    None when the target is not an importable package.
    """
    if not spec.target_module:
        return None, "no target module (non-package target)"
    code = (
        "import importlib, os, sys\n"
        f"m = importlib.import_module({spec.target_module!r})\n"
        "p = getattr(m, '__file__', None) or (list(getattr(m, '__path__', [])) or [''])[0]\n"
        "sys.stdout.write(os.path.realpath(p) if p else '')\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = spec.pythonpath
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [str(spec.python), "-B", "-c", code],
        cwd=str(spec.run_cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        return False, f"import failed: {result.stderr.strip()[:300]}"
    where = result.stdout.strip()
    root = os.path.realpath(spec.env_root)
    inside = bool(where) and (where == root or where.startswith(root + os.sep))
    return inside, where or "module resolved to no file"


#: Files at or below this size are hashed as well as stat'd.
HASH_SIZE_LIMIT = 2 * 1024 * 1024

Fingerprint = tuple[int, int, int, int, str]


def snapshot_tree(root: Path, hash_limit: int = HASH_SIZE_LIMIT) -> dict[str, Fingerprint]:
    """Fingerprint a tree, for the M10 before/after proof.

    ``(st_mtime_ns, st_size, st_ctime_ns, st_ino, md5)``.  Research §3.2 reports
    that ``st_ctime_ns`` cannot be set from userspace and so catches a
    forge-then-``os.utime()``-restore round trip.  **Measured here, that does not
    hold in general:** the kernel's file-timestamp clock advances on a timer tick,
    so a rewrite and its timestamp restoration executed inside one tick produce a
    fingerprint identical to the original, on ext4 and on tmpfs alike.  With a
    1.5 s gap the same round trip is caught.  So content is hashed rather than
    inferred; the stat fields stay because they are what catch a same-content
    inode swap.
    """
    out: dict[str, Fingerprint] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
        for name in filenames:
            fingerprint = _fingerprint(os.path.join(dirpath, name), hash_limit)
            if fingerprint is not None:
                out[os.path.join(dirpath, name)] = fingerprint
    return out


def _fingerprint(full: str, hash_limit: int) -> Fingerprint | None:
    """One file's fingerprint, or ``None`` if it is no longer there.

    A file that vanished between the walk and the stat is absent from this
    snapshot, which is exactly how a removal should read.
    """
    try:
        st = os.lstat(full)
    except OSError as exc:
        logger.debug("gone before stat: %s", full, exc_info=exc)
        return None
    digest = ""
    if stat.S_ISREG(st.st_mode) and st.st_size <= hash_limit:
        try:
            digest = hashlib.md5(Path(full).read_bytes()).hexdigest()
        except OSError as exc:
            logger.debug("unreadable while hashing: %s", full, exc_info=exc)
            digest = "unreadable"
    return (st.st_mtime_ns, st.st_size, st.st_ctime_ns, st.st_ino, digest)


def diff_snapshots(
    before: dict[str, Fingerprint],
    after: dict[str, Fingerprint],
) -> dict[str, list[str]]:
    """Added / removed / modified paths between two snapshots."""
    before_keys, after_keys = set(before), set(after)
    return {
        "added": sorted(after_keys - before_keys),
        "removed": sorted(before_keys - after_keys),
        "modified": sorted(k for k in before_keys & after_keys if before[k] != after[k]),
    }
