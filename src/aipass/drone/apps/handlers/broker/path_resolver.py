# =================== AIPass ====================
# Name: path_resolver.py
# Description: Kernel-safe path resolution via openat2 RESOLVE_BENEATH
# Version: 1.1.0
# Created: 2026-06-09
# Modified: 2026-09-12
# =============================================

"""Kernel-safe path resolution via openat2 RESOLVE_BENEATH.

Re-resolves an agent-supplied path string server-side so the broker never
trusts the raw string. Uses Linux openat2(2) with RESOLVE_BENEATH |
RESOLVE_NO_SYMLINKS to guarantee the final target is strictly beneath an
allowed base directory and traverses no symlinks.

Falls back to a pure-Python per-component walk (O_NOFOLLOW openat) when
openat2 is unavailable (non-Linux, older kernels). That fallback is the lane
every non-Linux host takes, so it holds the same containment contract with
portable spellings only -- no /proc, no hardcoded Linux flag numbers.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import stat
import struct
import sys
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler

RESOLVE_BENEATH = 0x08
RESOLVE_NO_SYMLINKS = 0x04
SYS_OPENAT2 = 437

# openat2(2) is handed raw kernel flags, so O_PATH here is the Linux number by
# definition. The walk below runs on hosts that spell these flags differently --
# 0o0400000 is O_NOFOLLOW on Linux and O_NOCTTY on macOS -- so it takes its own
# from `os`, which always carries the value of the host it is running on.
O_PATH = 0o010000000

_WALK_O_PATH = getattr(os, "O_PATH", 0)
_WALK_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_WALK_SUPPORTED = bool(_WALK_O_NOFOLLOW) and os.open in os.supports_dir_fd

_OPEN_HOW_SIZE = 24


def _openat2_available() -> bool:
    """Check if the openat2 syscall is usable on this platform."""
    return sys.platform == "linux" and os.uname().machine == "x86_64"


def _openat2(dirfd: int, pathname: bytes, flags: int, resolve: int) -> int:
    """Call openat2(2) via ctypes syscall.

    Returns an fd on success, raises OSError on failure.
    """
    open_how = struct.pack("QQQ", flags, 0, resolve)
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    result = libc.syscall(
        ctypes.c_long(SYS_OPENAT2),
        ctypes.c_int(dirfd),
        ctypes.c_char_p(pathname),
        ctypes.c_char_p(open_how),
        ctypes.c_size_t(_OPEN_HOW_SIZE),
    )
    if result < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), pathname.decode(errors="replace"))
    return result


def resolve_beneath(base: Path, relpath: str) -> Path:
    """Resolve *relpath* strictly beneath *base*, refusing escapes and symlinks.

    Uses openat2 RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS on Linux x86-64,
    falls back to a per-component O_NOFOLLOW walk otherwise.

    Returns the resolved absolute path on success.
    Raises OSError on traversal failure (escape, symlink, missing component).
    """
    json_handler.log_operation("resolve_beneath", {"base": str(base), "relpath": relpath})

    cleaned = os.path.normpath(relpath)
    if cleaned.startswith("/") or cleaned.startswith(".."):
        raise OSError(1, "Path escapes base via leading / or ..", relpath)

    parts = cleaned.split("/")
    if ".." in parts:
        raise OSError(1, "Path contains .. component", relpath)

    if _openat2_available():
        return _resolve_via_openat2(base, cleaned)
    return _resolve_via_walk(base, parts)


def _resolve_via_openat2(base: Path, cleaned: str) -> Path:
    """Resolve using the openat2 syscall with kernel-enforced containment."""
    dirfd = os.open(str(base), os.O_RDONLY | os.O_DIRECTORY)
    try:
        fd = _openat2(
            dirfd,
            cleaned.encode(),
            O_PATH,
            RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS,
        )
        try:
            resolved = Path(os.readlink(f"/proc/self/fd/{fd}"))
            logger.info("resolve_beneath: openat2 resolved %s -> %s", cleaned, resolved)
            return resolved
        finally:
            os.close(fd)
    finally:
        os.close(dirfd)


def _stat_leaf(component: str, dir_fd: int) -> os.stat_result:
    """Measure the last component relative to its already-verified parent.

    The leaf is stat'd, not opened: an open would need a read right the caller
    may not hold and would block on a fifo, and its identity is all the
    verification below asks for. A symlink is refused here exactly as
    O_NOFOLLOW refuses one on the components above it.
    """
    info = os.stat(component, dir_fd=dir_fd, follow_symlinks=False)
    if stat.S_ISLNK(info.st_mode):
        raise OSError(errno.ELOOP, "Symbolic link not followed", component)
    return info


def _verify_leaf(resolved: Path, leaf: os.stat_result, parts: list[str]) -> None:
    """Prove the path handed back still names the inode the walk verified.

    This is what the Linux lane gets from reading the fd's own path out of
    /proc, and there is no portable door to that. So the contract is closed
    from the other side: the walk verified an inode through fds, one per
    component, that no rename can redirect; the assembled path is returned only
    if it lstats to that same (device, inode) right now. Swap a component under
    the walk and the pair no longer matches, so the caller gets an error rather
    than a path pointing at something nobody checked.
    """
    try:
        seen = os.lstat(resolved)
    except OSError as exc:
        raise OSError(
            exc.errno,
            f"Resolved path went away mid-walk: {exc.strerror}",
            "/".join(parts),
        ) from exc

    if (seen.st_dev, seen.st_ino) != (leaf.st_dev, leaf.st_ino):
        raise OSError(
            errno.ESTALE,
            f"Resolved path changed under the walk: {resolved}",
            "/".join(parts),
        )


def _resolve_via_walk(base: Path, parts: list[str]) -> Path:
    """Fallback: per-component walk using O_NOFOLLOW to block symlinks."""
    if not _WALK_SUPPORTED:
        raise OSError(
            errno.ENOTSUP,
            "Path resolution needs O_NOFOLLOW and dir_fd support, and this host "
            "has neither -- refusing rather than resolving unverified",
            "/".join(parts),
        )

    components = [c for c in parts if c not in ("", ".")]
    current_fd = os.open(str(base), os.O_RDONLY | os.O_DIRECTORY)
    try:
        leaf = os.fstat(current_fd)
        for i, component in enumerate(components):
            try:
                if i == len(components) - 1:
                    leaf = _stat_leaf(component, current_fd)
                    break
                next_fd = os.open(
                    component,
                    _WALK_O_PATH | _WALK_O_NOFOLLOW | os.O_DIRECTORY,
                    dir_fd=current_fd,
                )
            except OSError as exc:
                raise OSError(
                    exc.errno,
                    f"Component '{component}' failed: {exc.strerror}",
                    "/".join(parts),
                ) from exc

            os.close(current_fd)
            current_fd = next_fd

        resolved = Path(os.path.realpath(base)).joinpath(*components)
        _verify_leaf(resolved, leaf, parts)
        logger.info("resolve_beneath: walk resolved %s -> %s", "/".join(parts), resolved)
        return resolved
    finally:
        os.close(current_fd)
