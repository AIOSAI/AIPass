# =================== AIPass ====================
# Name: system_detector.py
# Description: Pure system detection logic for aipass doctor
# Version: 1.0.1
# Created: 2026-04-16
# Modified: 2026-10-17
# =============================================

"""
System Detector — Pure detection logic for doctor checks.

No Rich markup — display concerns belong to the UI layer.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler


def detect_python(version_info: Any = sys.version_info) -> Dict[str, Any]:
    """Return Python version info and ok/warning flags.

    version_info is a test seam so sys is never replaced; product callers pass nothing.
    """
    info = version_info
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


def detect_git() -> Dict[str, Any]:
    """Return git availability and version string."""
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
        parts = raw.split()
        if len(parts) >= 3:
            version = parts[-1]
        else:
            version = raw
    except Exception as exc:
        logger.warning("[system_detector] git version check failed: %s", exc)

    return {"found": True, "version": version}


def _shell_from_parent_proc(os_name: str = os.name, getppid: Callable[[], int] = os.getppid) -> str | None:
    """POSIX fallback: read the invoking parent process's command name via /proc.

    Containers and CI runners often run a real shell without exporting $SHELL.
    """
    if os_name != "posix":
        return None
    try:
        comm_path = Path(f"/proc/{getppid()}/comm")
        if not comm_path.is_file():
            return None
        name = comm_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.info("[system_detector] /proc ppid comm read failed: %s", exc)
        return None
    return name or None


def detect_shell(os_name: str = os.name, getppid: Callable[[], int] = os.getppid) -> Dict[str, Any]:
    """Return shell name and path.

    os_name and getppid are test seams; product callers pass nothing.
    """
    shell_path = os.environ.get("SHELL", "")
    if shell_path:
        return {"name": Path(shell_path).name, "path": shell_path}

    name = _shell_from_parent_proc(os_name, getppid)
    if name:
        resolved = shutil.which(name)
        if resolved:
            return {"name": name, "path": resolved}
        return {"name": name, "path": ""}

    return {"name": "unknown", "path": ""}


def detect_os() -> Dict[str, Any]:
    """Return OS name, release, and machine architecture."""
    return {
        "os_name": platform.system() or "unknown",
        "release": platform.release() or "",
        "machine": platform.machine() or "",
    }


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
    """Return total RAM in GB and ok/warning flags."""
    total_gb = _total_ram_gb()
    ok = total_gb >= 4.0
    warning = 2.0 <= total_gb < 4.0
    result = {"total_gb": round(total_gb, 1), "ok": ok, "warning": warning}
    json_handler.log_operation("detect_ram", {"total_gb": result["total_gb"]}, "system_detector")
    return result


def detect_cpu() -> Dict[str, Any]:
    """Return logical CPU count."""
    count = os.cpu_count() or 0
    return {"count": count}


def detect_install_method() -> str:
    """Return how aipass was installed: 'pip', 'dev', 'clone', or 'fork'."""
    this_file = Path(__file__).resolve()

    if "site-packages" in str(this_file):
        return "pip"

    for parent in this_file.parents:
        if (parent / ".git").exists():
            if (parent / "pyproject.toml").exists() and (parent / "src").exists():
                return "dev"
            return "clone"

    return "unknown"


def detect_tmux() -> bool:
    """True if tmux is available on PATH."""
    return shutil.which("tmux") is not None


def detect_wt() -> bool:
    """True if Windows Terminal (wt.exe) is available on PATH."""
    return shutil.which("wt.exe") is not None


def detect_docker() -> bool:
    """True if docker is available on PATH."""
    return shutil.which("docker") is not None
