# =================== AIPass ====================
# Name: export_handler.py
# Description: The tracked tree at a ref, written into an empty directory
# Version: 1.0.0
# Created: 2026-10-04
# Modified: 2026-10-04
# =============================================

"""The tracked tree at a ref, written into an empty directory: the twin of ``git archive | tar -x``.

seedgo's CI-versus-local audits need a clean tracked tree (DPLAN-0195), and
with raw git blocked for every seat (git_gate 5.0.0) nothing else makes one.
It reads the repo and writes only the named directory, which must be empty
and sit under the host temp dir or the caller's own ``docs.local``. The
archive is unpacked with tarfile's ``data`` filter: no shell, no absolute or
escaping member, no device file.
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler


def temp_roots() -> list[Path]:
    """The host's temp directories an export may write under: the temp dir, and /tmp on POSIX."""
    roots = [Path(tempfile.gettempdir()).resolve()]
    if sys.platform != "win32":
        roots.append(Path("/tmp").resolve())
    return roots


def _refused(message: str) -> dict:
    logger.warning("git export refused: %s", message)
    return {"success": False, "message": f"export refused: {message}"}


def export_tree(repo_root: Path, ref: str, dest: Path, docs_local: Path | None) -> dict:
    """Write the tracked tree at *ref* into *dest*.

    Args:
        repo_root: The repository to read.
        ref: Any name git resolves to a commit. A flag-shaped ref is refused.
        dest: An absolute directory. It is created if absent and must be empty.
        docs_local: The caller's own docs.local, the second allowed home, or None.

    Returns:
        Dict with success (bool) and message (str).
    """
    if ref.startswith("-"):
        return _refused(f"{ref} is not a commit")
    verify = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if verify.returncode != 0:
        return _refused(f"{ref} is not a commit")
    sha = verify.stdout.strip()

    target = dest.resolve()
    homes = temp_roots() + ([docs_local.resolve()] if docs_local is not None else [])
    if not any(target != home and target.is_relative_to(home) for home in homes):
        return _refused(f"{dest} is not under {' or '.join(str(home) for home in homes)}")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        return _refused(f"{dest} is not empty")
    target.mkdir(parents=True, exist_ok=True)

    archive = subprocess.Popen(
        ["git", "archive", "--format=tar", sha], cwd=str(repo_root), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    files = 0
    try:
        with tarfile.open(fileobj=archive.stdout, mode="r|") as stream:
            for member in stream:
                stream.extract(member, target, filter="data")
                files += member.isfile()
    except (tarfile.TarError, OSError) as exc:
        archive.kill()
        archive.wait()
        logger.error("git export of %s into %s failed: %s", ref, target, exc)
        return {"success": False, "message": f"export failed: {exc} ({target} may hold part of the tree)"}
    stderr = archive.stderr.read().decode("utf-8", "replace") if archive.stderr else ""
    if archive.wait() != 0:
        return {"success": False, "message": f"git archive failed: {stderr.strip()}"}

    message = f"Exported {ref} ({sha[:7]}) to {dest}: {files} file(s)"
    json_handler.log_operation("git_export", {"ref": ref, "commit": sha, "dest": str(target), "files": files})
    logger.info(message)
    return {"success": True, "message": message}
