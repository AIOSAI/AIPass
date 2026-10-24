# =================== AIPass ====================
# Name: path_resolver.py
# Description: Kernel-safe path resolution via openat2 RESOLVE_BENEATH
# Version: 1.1.3
# Created: 2026-06-09
# Modified: 2026-10-23
# =============================================

"""Kernel-safe path resolution via openat2 RESOLVE_BENEATH.

The O_NOFOLLOW walk fallback is every non-Linux host's lane: same contract, portable spellings only.
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

# openat2 takes raw Linux flag numbers; the walk takes host values from `os` (flag numbers differ on macOS).
O_PATH = 0o010000000
O_DIRECTORY = 0o200000

_WALK_O_PATH = getattr(os, "O_PATH", 0)
_WALK_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_WALK_SUPPORTED = bool(_WALK_O_NOFOLLOW) and os.open in os.supports_dir_fd

_OPEN_HOW_SIZE = 24


def _openat2_available() -> bool:
    """Check if the openat2 syscall is usable on this platform."""
    return sys.platform == "linux" and os.uname().machine == "x86_64"


def _openat2(dirfd: int, pathname: bytes, flags: int, resolve: int) -> int:
    """Call openat2(2) via ctypes syscall; returns an fd, raises OSError on failure."""
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
    """Resolve *relpath* strictly beneath *base*, refusing escapes and symlinks (OSError)."""
    parent_fd, name, resolved = open_parent_beneath(base, relpath)
    try:
        if name:
            _stat_leaf(name, parent_fd)
    finally:
        os.close(parent_fd)
    return resolved


def open_parent_beneath(base: Path, relpath: str) -> tuple[int, str, Path]:
    """Open *relpath*'s parent strictly beneath *base*, following no symlink; the leaf must exist.

    Returns ``(parent fd, leaf name, leaf path)``; the caller closes the fd. The leaf is lstat'd,
    never followed, so it may be a symlink. Leaf name ``""`` means *relpath* is the base itself.
    """
    json_handler.log_operation("resolve_beneath", {"base": str(base), "relpath": relpath})

    cleaned = os.path.normpath(relpath)
    if cleaned.startswith("/") or cleaned.startswith(".."):
        raise OSError(1, "Path escapes base via leading / or ..", relpath)

    parts = cleaned.split("/")
    if ".." in parts:
        raise OSError(1, "Path contains .. component", relpath)

    components = [c for c in parts if c not in ("", ".")]
    parent, name = components[:-1], components[-1] if components else ""
    if _openat2_available():
        try:
            return _open_via_openat2(base, parent, name)
        except OSError as exc:
            if exc.errno != errno.ENOSYS:
                raise
    return _open_via_walk(base, parent, name, parts)


def _fd_path(fd: int) -> Path:
    """The path the kernel holds for an open fd, read out of /proc (Linux openat2 lane only).

    Test seam: tests replace it with a failing reader to prove the walk never reaches /proc.
    """
    return Path(os.readlink(f"/proc/self/fd/{fd}"))


def _open_via_openat2(base: Path, parent: list[str], name: str) -> tuple[int, str, Path]:
    """Open the parent with the openat2 syscall: kernel-enforced containment."""
    dirfd = os.open(str(base), os.O_RDONLY | os.O_DIRECTORY)
    try:
        fd = _openat2(
            dirfd,
            "/".join(parent).encode() or b".",
            O_PATH | O_DIRECTORY,
            RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS,
        )
    finally:
        os.close(dirfd)
    try:
        if name:
            os.stat(name, dir_fd=fd, follow_symlinks=False)
        resolved = _fd_path(fd) / name
    except BaseException:
        os.close(fd)
        raise
    logger.info("resolve_beneath: openat2 resolved %s -> %s", "/".join([*parent, name]), resolved)
    return fd, name, resolved


def _stat_leaf(component: str, dir_fd: int) -> os.stat_result:
    """Measure the last component relative to its already-verified parent.

    Stat, not open: an open needs a read right and blocks on a fifo. Symlinks are refused.
    """
    info = os.stat(component, dir_fd=dir_fd, follow_symlinks=False)
    if stat.S_ISLNK(info.st_mode):
        raise OSError(errno.ELOOP, "Symbolic link not followed", component)
    return info


def _verify_leaf(resolved: Path, leaf: os.stat_result, parts: list[str]) -> None:
    """Prove the path handed back still names the inode the walk verified.

    The portable stand-in for /proc: a component swapped under the walk changes (dev, ino).
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


def _real_base(base: Path) -> Path:
    """The base named by its real path — the string the walk's answer is rebuilt from.

    Read by name after the walk, hence _verify_leaf. Test seam: tests stage a rename here.
    """
    return Path(os.path.realpath(base))


def _open_via_walk(base: Path, parent: list[str], name: str, parts: list[str]) -> tuple[int, str, Path]:
    """Fallback: open the parent component by component with O_NOFOLLOW to block symlinks."""
    if not _WALK_SUPPORTED:
        raise OSError(
            errno.ENOTSUP,
            "Path resolution needs O_NOFOLLOW and dir_fd support, and this host "
            "has neither -- refusing rather than resolving unverified",
            "/".join(parts),
        )

    current_fd = os.open(str(base), os.O_RDONLY | os.O_DIRECTORY)
    try:
        leaf = os.fstat(current_fd)
        for i, component in enumerate([*parent, name] if name else parent):
            try:
                if i == len(parent):
                    leaf = os.stat(component, dir_fd=current_fd, follow_symlinks=False)
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

        resolved = _real_base(base).joinpath(*parent, name)
        _verify_leaf(resolved, leaf, parts)
        logger.info("resolve_beneath: walk resolved %s -> %s", "/".join(parts), resolved)
        return current_fd, name, resolved
    except BaseException:
        os.close(current_fd)
        raise
