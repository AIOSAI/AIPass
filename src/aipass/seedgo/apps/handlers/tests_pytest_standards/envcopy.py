# =================== AIPass ====================
# Name: envcopy.py
# Description: copy-first scratch environment for the pytest adapter (Law M10)
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The scratch environment a suite is measured inside. Law M10 made concrete.

The instrument must not disturb what it measures, so no suite is ever run in
place. The MVP's calibration proved why in numbers, not in principle: scoring
@daemon where it lives forges 31 events into its real rotation log, and
@backup's suite rewrites its real backup_timestamps.json.

TWO LAYOUTS, ONE BUILDER:

  aipass  the target sits at <repo>/src/aipass/<name> and branches import each
          other as `aipass.<sibling>.apps...`, so the env mirrors that layout
          and PYTHONPATH puts <env>/src AHEAD of the editable install's .pth
          entry. Without that ordering `aipass.<name>` resolves to the real
          repo and every number below describes a tree we may not touch.
  plain   any other directory holding pytest targets. Copied whole.

COPY-ALWAYS IS THE DEFAULT, and it inverts the MVP's (design C10). Symlinking
siblings is faster and a write through a symlink really lands in the real
tree — measured: the MVP's first calibration run on @backup put five files into
the REAL prax/prax_json/ through one. A default that can write the real repo is
not a default an auditor may ship. `symlink_siblings=True` is available as a
speed flag and it stamps `m10_complete: false` on the run that chose it.

THE EXCLUDE SET IS PART OF THE CONTRACT, not an implementation detail. It is
the difference between a 3-second copy and a 157 MB one: memory/.chroma is a
live vector store of that size, measured, and copy-always would rsync it on
every run — with a torn read if the store is mid-write.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

#: Never copied. `.chroma`, `.venv` and `node_modules` are the three the MVP's
#: set omitted; each is large enough to change what the lane costs to run.
RSYNC_EXCLUDES: Tuple[str, ...] = (
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    ".git",
    ".chroma",
    ".venv",
    "node_modules",
)

#: Wall-clock ceiling on one rsync. A copy that hangs must not become a hang
#: of the whole lane; T-BUDGET covers the suite, this covers the setup.
COPY_TIMEOUT_SECONDS = 900


class EnvError(RuntimeError):
    """The environment could not be built, or is not the one we would measure."""


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
    copied_siblings: List[str] = field(default_factory=list)
    symlinked_siblings: List[str] = field(default_factory=list)

    @property
    def m10_complete(self) -> bool:
        """True when nothing in this env can write through to the real tree.

        A symlinked sibling is writable and a write through one lands in the
        real repo, so M10 holds for the target alone rather than for the whole
        env. The artifact stamps this rather than assuming it.
        """
        return not self.symlinked_siblings

    def to_document(self) -> dict:
        """The artifact's environment block."""
        return {
            "layout": self.layout,
            "env_root": str(self.env_root),
            "target_copy": str(self.target_copy),
            "target_module": self.target_module,
            "python": str(self.python),
            "copied_siblings": list(self.copied_siblings),
            "symlinked_siblings": list(self.symlinked_siblings),
            "m10_complete": self.m10_complete,
            "excludes": list(RSYNC_EXCLUDES),
        }


# =============================================================================
# RESOLUTION
# =============================================================================


def find_python(target: Path, override: Optional[str] = None) -> Path:
    """Resolve the interpreter that owns the target's dependencies.

    Order: explicit argument, `AUDIT_TESTS_PYTHON`, the nearest `.venv` walking
    up from the target, then this interpreter. No path is hardcoded — a checker
    that only runs on one machine is not a checker.

    Symlinks are deliberately NOT resolved. `.venv/bin/python` is a symlink to
    the system interpreter, and resolving it hands back a python that cannot
    see the venv's site-packages; the MVP found this as a first run reporting
    `No module named pytest`.
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


def detect_layout(target: Path) -> Tuple[str, Optional[Path]]:
    """Return `(layout, repo_root)`; repo_root is None for a plain target."""
    parent, grandparent = target.parent, target.parent.parent
    if parent.name == "aipass" and grandparent.name == "src":
        return "aipass", grandparent.parent
    return "plain", None


# =============================================================================
# THE COPY
# =============================================================================


def rsync(source: Path, destination: Path) -> None:
    """One rsync with the contract's excludes. Raises EnvError on failure.

    Never falls back to a partial copy: an env built from an incomplete tree
    would produce a measurement of something that does not exist.
    """
    destination.mkdir(parents=True, exist_ok=True)
    excludes: List[str] = []
    for name in RSYNC_EXCLUDES:
        excludes += ["--exclude", name]

    command = ["rsync", "-a", "--delete", *excludes, f"{source}/", f"{destination}/"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=COPY_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise EnvError(f"rsync of {source} could not complete: {type(exc).__name__}: {exc}") from exc

    if result.returncode != 0:
        raise EnvError(f"rsync of {source} failed ({result.returncode}): {result.stderr.strip()[:400]}")


def _place_siblings(real_src: Path, src_dir: Path, skip: str, symlink: bool) -> Tuple[List[str], List[str]]:
    """Copy or symlink every sibling package. Returns `(copied, symlinked)`."""
    copied: List[str] = []
    symlinked: List[str] = []

    for entry in sorted(real_src.iterdir()):
        if not entry.is_dir() or entry.name in ("__pycache__", skip):
            continue
        if symlink:
            (src_dir / entry.name).symlink_to(entry)
            symlinked.append(entry.name)
        else:
            rsync(entry, src_dir / entry.name)
            copied.append(entry.name)

    return copied, symlinked


def _build_aipass_env(target: Path, env_root: Path, repo_root: Path, symlink: bool) -> dict:
    """Mirror the `src/aipass/<name>` layout inside the scratch env."""
    src_dir = env_root / "src" / "aipass"
    src_dir.mkdir(parents=True)
    real_src = repo_root / "src" / "aipass"

    for name in ("__init__.py", "conftest.py"):
        if (real_src / name).is_file():
            shutil.copy2(real_src / name, src_dir / name)
    if (repo_root / "conftest.py").is_file():
        shutil.copy2(repo_root / "conftest.py", env_root / "conftest.py")

    copied, symlinked = _place_siblings(real_src, src_dir, target.name, symlink)
    target_copy = src_dir / target.name
    rsync(target, target_copy)

    return {
        "target_copy": target_copy,
        "run_cwd": env_root,
        "test_arg": str(Path("src") / "aipass" / target.name / "tests"),
        "target_module": f"aipass.{target.name}",
        "pythonpath": str(env_root / "src"),
        "copied_siblings": copied,
        "symlinked_siblings": symlinked,
    }


def _build_plain_env(target: Path, env_root: Path) -> dict:
    """Copy an ordinary directory whole. Nothing is symlinked."""
    target_copy = env_root / target.name
    rsync(target, target_copy)
    return {
        "target_copy": target_copy,
        "run_cwd": env_root,
        "test_arg": target.name,
        "target_module": "",
        "pythonpath": str(env_root),
        "copied_siblings": [],
        "symlinked_siblings": [],
    }


def build_env(
    target: Path,
    env_root: Path,
    plugin_source: Path,
    python_override: Optional[str] = None,
    symlink_siblings: bool = False,
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

    if layout == "aipass" and repo_root is not None:
        built = _build_aipass_env(target, env_root, repo_root, symlink_siblings)
    else:
        built = _build_plain_env(target, env_root)

    target_copy: Path = built["target_copy"]
    run_cwd: Path = built["run_cwd"]
    test_arg: str = built["test_arg"]
    if not (target_copy / "tests").is_dir():
        # Not every project puts its tests under tests/; point pytest at the
        # copy itself rather than at a directory that is not there.
        test_arg = str(target_copy.relative_to(run_cwd))

    spec = EnvSpec(
        layout=layout,
        env_root=env_root,
        run_cwd=run_cwd,
        target_copy=target_copy,
        target_module=built["target_module"],
        test_arg=test_arg,
        python=find_python(target, python_override),
        pythonpath=os.pathsep.join([built["pythonpath"], str(plugin_dir)]),
        plugin_dir=plugin_dir,
        log_path=log_path,
        copied_siblings=built["copied_siblings"],
        symlinked_siblings=built["symlinked_siblings"],
    )

    # Recorded because `m10_complete: false` is the one env state a reader
    # must be able to find later: it means a write could have reached the real
    # repo through a symlinked sibling.
    json_handler.log_operation(
        "scratch_env_built",
        {
            "layout": layout,
            "copied_siblings": len(spec.copied_siblings),
            "symlinked_siblings": len(spec.symlinked_siblings),
            "m10_complete": spec.m10_complete,
        },
    )
    return spec


# =============================================================================
# HARNESS CHECK 3 - THE COPY MUST BE WHAT LOADS
# =============================================================================


def assert_copy_is_live(spec: EnvSpec, timeout: int = 120) -> Tuple[Optional[bool], str]:
    """Import the target in a child and report where it actually resolved.

    Returns `(verified, detail)`; verified is None when the target is not an
    importable package, which is a legitimate state and not a failure.

    This is the check that catches the worst possible outcome of the whole
    lane: an editable install resolving `aipass.*` back to the real repo, so
    the suite runs against the tree we promised not to touch and the artifact
    reports it as a measurement of the copy.
    """
    if not spec.target_module:
        return None, "no target module (non-package target)"

    code = (
        "import importlib, os, sys\n"
        f"m = importlib.import_module({spec.target_module!r})\n"
        "p = getattr(m, '__file__', None) or (list(getattr(m, '__path__', [])) or [''])[0]\n"
        "sys.stdout.write(os.path.realpath(p) if p else '')\n"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = spec.pythonpath
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    try:
        result = subprocess.run(
            [str(spec.python), "-B", "-c", code],
            cwd=str(spec.run_cwd),
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning(f"[AUDIT-TESTS] liveness probe could not run: {exc}")
        return False, f"probe failed to run: {type(exc).__name__}: {exc}"

    if result.returncode != 0:
        return False, f"import failed: {result.stderr.strip()[:300]}"

    where = result.stdout.strip()
    root = os.path.realpath(spec.env_root)
    inside = bool(where) and (where == root or where.startswith(root + os.sep))
    return inside, where or "module resolved to no file"
