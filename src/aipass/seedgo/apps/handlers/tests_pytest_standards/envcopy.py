# =================== AIPass ====================
# Name: envcopy.py
# Description: copy-first scratch environment for the pytest adapter (Law M10)
# Version: 1.2.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""The scratch environment a suite is measured inside. Law M10 made concrete.

No suite runs in place. <env>/src goes ahead of the editable install's .pth, or
`aipass.<name>` resolves to the real repo. Siblings are copied by default: a
symlinked sibling writes through. The exclude set is part of the contract.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.tests_pytest_standards.diff_scope import DiffScope, read_scope

#: Never copied; each entry is large or live enough to change what the lane costs.
RSYNC_EXCLUDES: Tuple[str, ...] = (
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    ".git",
    ".chroma",
    ".venv",
    "node_modules",
    # prax's atomic-write staging files live for microseconds and race a live copy;
    # excluded by pattern because the settled json is part of the tree.
    ".*_*.tmp",
)

#: 24 = files vanished mid-transfer (the tree moved), not a partial copy. Tolerated,
#: not ignored: stderr is recorded in `vanished_during_copy`.
RSYNC_WARNING_CODES: Tuple[int, ...] = (24,)

#: T-BUDGET covers the suite; this keeps a hung copy from hanging the lane.
COPY_TIMEOUT_SECONDS = 900

NO_EXECUTION_GROUPS: Tuple[str, ...] = ()


#: Published on the spec: siblings from a different tree than the target must be findable.
SIBLINGS_FROM_OWN_ROOT = "own_root"
SIBLINGS_FROM_HOST_REPO = "host_repo"


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

    #: Tolerated rsync warnings, verbatim: the fleet was moving under the copy.
    vanished_during_copy: List[str] = field(default_factory=list)

    #: `host_repo` when a banked fixture borrows the running checkout's siblings.
    sibling_basis: str = SIBLINGS_FROM_OWN_ROOT

    #: On the spec because the spec is the only thing `nominate()` receives.
    execution_groups: List[str] = field(default_factory=list)

    #: Read from the real target before the copy: `.git` never reaches the scratch env.
    diff_scope: Optional[DiffScope] = None

    #: The operator's `--budget` for the mutation campaigns; None is each campaign's default.
    campaign_budget_seconds: Optional[int] = None

    @property
    def m10_complete(self) -> bool:
        """True when nothing in this env can write through to the real tree."""
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
            "sibling_basis": self.sibling_basis,
            "m10_complete": self.m10_complete,
            "excludes": list(RSYNC_EXCLUDES),
            "vanished_during_copy": list(self.vanished_during_copy),
            "diff_scope": None if self.diff_scope is None else self.diff_scope.to_document(),
            # Published so an opted-in run and a default run never produce the same document.
            "execution_groups": list(self.execution_groups),
            "campaign_budget_seconds": self.campaign_budget_seconds,
        }


def find_python(target: Path, override: Optional[str] = None) -> Path:
    """Resolve the interpreter that owns the target's dependencies.

    Symlinks are not resolved: `.venv/bin/python` resolved is a python that cannot see
    the venv's site-packages.
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


def rsync(source: Path, destination: Path) -> Optional[str]:
    """One rsync with the contract's excludes. Raises EnvError on failure.

    Never a partial copy. A `RSYNC_WARNING_CODES` exit is returned as a warning string.
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

    if result.returncode in RSYNC_WARNING_CODES:
        warning = f"rsync of {source} warned ({result.returncode}): {result.stderr.strip()[:400]}"
        logger.warning("[audit_tests] %s", warning)
        return warning

    if result.returncode != 0:
        raise EnvError(f"rsync of {source} failed ({result.returncode}): {result.stderr.strip()[:400]}")

    return None


def _place_siblings(real_src: Path, src_dir: Path, skip: str, symlink: bool) -> Tuple[List[str], List[str], List[str]]:
    """Copy or symlink every sibling package."""
    copied: List[str] = []
    symlinked: List[str] = []
    warnings: List[str] = []

    for entry in sorted(real_src.iterdir()):
        if not entry.is_dir() or entry.name in ("__pycache__", skip):
            continue
        if symlink:
            (src_dir / entry.name).symlink_to(entry)
            symlinked.append(entry.name)
        else:
            warning = rsync(entry, src_dir / entry.name)
            if warning is not None:
                warnings.append(warning)
            copied.append(entry.name)

    return copied, symlinked, warnings


def _has_siblings(real_src: Path, skip: str) -> bool:
    """Whether this `src/aipass` holds any package other than the target."""
    if not real_src.is_dir():
        return False
    return any(e.is_dir() and e.name not in ("__pycache__", skip) for e in real_src.iterdir())


def host_repo_root() -> Optional[Path]:
    """The real AIPass checkout this code is running from, or None.

    Walks up for a directory holding `src/aipass`; a parent count breaks when the file moves.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "src" / "aipass").is_dir():
            return candidate
    return None


def sibling_source(repo_root: Path, target_name: str) -> Tuple[Path, str]:
    """Where to take sibling packages from, and which choice was made.

    A banked fixture has no siblings and `aipass` is a regular package, so its own `src`
    first would hide every real sibling; they come from the running checkout instead.
    """
    own_src = repo_root / "src" / "aipass"
    if _has_siblings(own_src, target_name):
        return own_src, SIBLINGS_FROM_OWN_ROOT

    host_root = host_repo_root()
    host_src = None if host_root is None else host_root / "src" / "aipass"
    if host_src is not None and _has_siblings(host_src, target_name):
        return host_src, SIBLINGS_FROM_HOST_REPO

    raise EnvError(
        f"no sibling packages for {target_name}: neither {own_src} nor {host_src} holds another "
        "aipass package, so the copy could not import aipass.prax and the suite could not run"
    )


def _build_aipass_env(target: Path, env_root: Path, repo_root: Path, symlink: bool) -> dict:
    """Mirror the `src/aipass/<name>` layout inside the scratch env."""
    src_dir = env_root / "src" / "aipass"
    src_dir.mkdir(parents=True)
    real_src, sibling_basis = sibling_source(repo_root, target.name)

    for name in ("__init__.py", "conftest.py"):
        if (real_src / name).is_file():
            shutil.copy2(real_src / name, src_dir / name)
    root_conftest = repo_root / "conftest.py"
    host_root = host_repo_root()
    if not root_conftest.is_file() and sibling_basis == SIBLINGS_FROM_HOST_REPO and host_root is not None:
        root_conftest = host_root / "conftest.py"
    if root_conftest.is_file():
        shutil.copy2(root_conftest, env_root / "conftest.py")

    copied, symlinked, warnings = _place_siblings(real_src, src_dir, target.name, symlink)
    target_copy = src_dir / target.name
    target_warning = rsync(target, target_copy)
    if target_warning is not None:
        warnings.append(target_warning)

    return {
        "target_copy": target_copy,
        "run_cwd": env_root,
        "test_arg": str(Path("src") / "aipass" / target.name / "tests"),
        "target_module": f"aipass.{target.name}",
        "pythonpath": str(env_root / "src"),
        "copied_siblings": copied,
        "symlinked_siblings": symlinked,
        "sibling_basis": sibling_basis,
        "vanished_during_copy": warnings,
    }


def _build_plain_env(target: Path, env_root: Path) -> dict:
    """Copy an ordinary directory whole. Nothing is symlinked."""
    target_copy = env_root / target.name
    warning = rsync(target, target_copy)
    return {
        "target_copy": target_copy,
        "vanished_during_copy": [warning] if warning is not None else [],
        "run_cwd": env_root,
        "test_arg": target.name,
        "target_module": "",
        "pythonpath": str(env_root),
        "copied_siblings": [],
        "symlinked_siblings": [],
    }


def normalise_execution_groups(requested: Optional[Sequence[str]]) -> List[str]:
    """The opt-in list, de-duplicated and in the order it was asked for."""
    groups: List[str] = []
    for name in requested or NO_EXECUTION_GROUPS:
        text = str(name)
        if text and text not in groups:
            groups.append(text)
    return groups


def _resolve_diff_scope(
    target: Path, repo_root: Optional[Path], ref: Optional[str], requested: bool
) -> Optional[DiffScope]:
    """The change set, or None when nothing asked for one.

    Refuses rather than widening: no repository would mean an empty scope and a clean run.
    """
    if not requested:
        return None
    if repo_root is None:
        raise EnvError(
            f"--diff-scope was asked for but {target} is not inside a repository, so there is no "
            "change set to read; an empty scope would probe nothing and report it as clean"
        )
    return read_scope(target, repo_root, ref)


def build_env(
    target: Path,
    env_root: Path,
    plugin_source: Path,
    python_override: Optional[str] = None,
    symlink_siblings: bool = False,
    execution_groups: Optional[Sequence[str]] = None,
    diff_scope_ref: Optional[str] = None,
    scope_to_diff: bool = False,
    campaign_budget_seconds: Optional[int] = None,
) -> EnvSpec:
    """Materialise the scratch env and return how to run pytest inside it."""
    target = target.resolve()
    layout, repo_root = detect_layout(target)
    env_root = env_root.resolve()

    # Before the copy: `.git` never reaches the scratch env.
    scope = _resolve_diff_scope(target, repo_root, diff_scope_ref, scope_to_diff)

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
        sibling_basis=built.get("sibling_basis", SIBLINGS_FROM_OWN_ROOT),
        vanished_during_copy=built.get("vanished_during_copy", []),
        execution_groups=normalise_execution_groups(execution_groups),
        diff_scope=scope,
        campaign_budget_seconds=campaign_budget_seconds,
    )

    # `m10_complete: false` must be findable later: a write could have reached the real repo.
    json_handler.log_operation(
        "scratch_env_built",
        {
            "layout": layout,
            "copied_siblings": len(spec.copied_siblings),
            "symlinked_siblings": len(spec.symlinked_siblings),
            "m10_complete": spec.m10_complete,
            "execution_groups": list(spec.execution_groups),
        },
    )
    return spec


def assert_copy_is_live(spec: EnvSpec, timeout: int = 120) -> Tuple[Optional[bool], str]:
    """Import the target in a child and report where it actually resolved.

    Catches an editable install resolving `aipass.*` back to the real repo.
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
