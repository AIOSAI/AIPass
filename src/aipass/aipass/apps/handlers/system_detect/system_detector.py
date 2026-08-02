# =================== AIPass ====================
# Name: system_detector.py
# Description: Pure system detection logic for aipass doctor
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""
System Detector — Pure detection logic for doctor checks.

Returns plain dicts with facts about the running environment.
No Rich markup — display concerns belong to the UI layer.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler

# =============================================================================
# PYTHON
# =============================================================================


def detect_python() -> Dict[str, Any]:
    """Return Python version info and ok/warning flags.

    Returns:
        version: str like "3.11.5"
        major: int
        minor: int
        ok: bool — True if >=3.9
        warning: bool — True if ==3.8 (supported but near end)
    """
    info = sys.version_info
    version = f"{info.major}.{info.minor}.{info.micro}"
    ok = (info.major, info.minor) >= (3, 9)
    warning = (info.major, info.minor) == (3, 8)
    return {
        "version": version,
        "major": info.major,
        "minor": info.minor,
        "ok": ok,
        "warning": warning,
    }


# =============================================================================
# GIT
# =============================================================================


def detect_git() -> Dict[str, Any]:
    """Return git availability and version string.

    Returns:
        found: bool
        version: str — e.g. "2.43.0" or ""
    """
    git_path = shutil.which("git")
    if git_path is None:
        return {"found": False, "version": ""}

    version = ""
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        raw = result.stdout.strip()
        # "git version 2.43.0" → "2.43.0"
        parts = raw.split()
        if len(parts) >= 3:
            version = parts[-1]
        else:
            version = raw
    except Exception as exc:
        logger.warning("[system_detector] git version check failed: %s", exc)

    return {"found": True, "version": version}


# =============================================================================
# SHELL
# =============================================================================


def _shell_from_parent_proc() -> str | None:
    """POSIX fallback: read the invoking parent process's command name via /proc.

    Many containers/CI runners don't export $SHELL even though a real shell
    (bash/sh) is running the process — this is knowable via /proc/<ppid>/comm
    on Linux. Returns None if unavailable (non-Linux, /proc missing, read
    failure) — callers should keep the existing "unknown" fallback.
    """
    if os.name != "posix":
        return None
    try:
        comm_path = Path(f"/proc/{os.getppid()}/comm")
        if not comm_path.is_file():
            return None
        name = comm_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.info("[system_detector] /proc ppid comm read failed: %s", exc)
        return None
    return name or None


def detect_shell() -> Dict[str, Any]:
    """Return shell name and path.

    Falls back to the parent process's command name (via /proc/<ppid>/comm on
    Linux) when $SHELL isn't set — common in containers/CI runners that don't
    export it even though a real shell is running the process.

    Returns:
        name: str — e.g. "bash", "zsh", or "unknown"
        path: str — full path or ""
    """
    shell_path = os.environ.get("SHELL", "")
    if shell_path:
        return {"name": Path(shell_path).name, "path": shell_path}

    name = _shell_from_parent_proc()
    if name:
        resolved = shutil.which(name)
        if resolved:
            return {"name": name, "path": resolved}
        return {"name": name, "path": ""}

    return {"name": "unknown", "path": ""}


# =============================================================================
# OS
# =============================================================================


def detect_os() -> Dict[str, Any]:
    """Return OS name, release, and machine architecture.

    Returns:
        os_name: str — "Linux", "Darwin", "Windows", etc.
        release: str — kernel/OS release string
        machine: str — e.g. "x86_64"
    """
    return {
        "os_name": platform.system() or "unknown",
        "release": platform.release() or "",
        "machine": platform.machine() or "",
    }


# =============================================================================
# RAM
# =============================================================================


def _read_meminfo_kb() -> int:
    """Read MemTotal from /proc/meminfo and return value in kB, or 0 on failure."""
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return 0
    try:
        with open(meminfo, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1])
    except Exception as exc:
        logger.warning("[system_detector] /proc/meminfo read failed: %s", exc)
    return 0


def _total_ram_gb() -> float:
    """Return total RAM in GB using psutil or /proc/meminfo fallback."""
    try:
        import psutil  # type: ignore[import-untyped]

        return psutil.virtual_memory().total / (1024**3)
    except ImportError as exc:
        logger.info("[system_detector] psutil not installed, using /proc/meminfo fallback: %s", exc)
        kb = _read_meminfo_kb()
        return kb / (1024**2) if kb else 0.0
    except Exception as exc:
        logger.warning("[system_detector] psutil RAM check failed: %s", exc)
        return 0.0


def detect_ram() -> Dict[str, Any]:
    """Return total RAM in GB and ok/warning flags.

    Tries psutil first, falls back to /proc/meminfo on Linux, else 0.

    Returns:
        total_gb: float
        ok: bool — True if >=4 GB
        warning: bool — True if 2<=x<4 GB
    """
    total_gb = _total_ram_gb()
    ok = total_gb >= 4.0
    warning = 2.0 <= total_gb < 4.0
    result = {"total_gb": round(total_gb, 1), "ok": ok, "warning": warning}
    json_handler.log_operation("detect_ram", {"total_gb": result["total_gb"]}, "system_detector")
    return result


# =============================================================================
# CPU
# =============================================================================


def detect_cpu() -> Dict[str, Any]:
    """Return logical CPU count.

    Returns:
        count: int — number of logical CPUs (0 if unknown)
    """
    count = os.cpu_count() or 0
    return {"count": count}


# =============================================================================
# INSTALL METHOD
# =============================================================================


def detect_install_method() -> str:
    """Return how aipass was installed: 'pip', 'dev', 'clone', or 'fork'.

    Logic:
      - If this file's path contains 'site-packages' → pip
      - If .git exists AND pyproject.toml is in the same tree → dev (editable install / source contributor)
      - If .git exists → clone
      - Default → 'unknown'
    """
    this_file = Path(__file__).resolve()

    if "site-packages" in str(this_file):
        return "pip"

    for parent in this_file.parents:
        if (parent / ".git").exists():
            if (parent / "pyproject.toml").exists() and (parent / "src").exists():
                return "dev"
            return "clone"

    return "unknown"


# =============================================================================
# OPTIONAL TOOLS
# =============================================================================


def detect_tmux() -> bool:
    """True if tmux is available on PATH."""
    return shutil.which("tmux") is not None


def detect_wt() -> bool:
    """True if Windows Terminal (wt.exe) is available on PATH."""
    return shutil.which("wt.exe") is not None


def detect_docker() -> bool:
    """True if docker is available on PATH."""
    return shutil.which("docker") is not None
