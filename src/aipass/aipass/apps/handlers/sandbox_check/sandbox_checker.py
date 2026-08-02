# =================== AIPass ====================
# Name: sandbox_checker.py
# Description: Kernel sandbox prerequisite checks for aipass doctor
# Version: 1.0.0
# Created: 2026-06-10
# Modified: 2026-06-10
# =============================================

"""Sandbox prerequisite checker — detects bwrap, node, srt, rg, broker.

Returns plain dicts with facts about sandbox readiness.
No Rich markup — display concerns belong to the UI layer.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler


def check_sandbox_flag() -> Dict[str, Any]:
    """Check AIPASS_SANDBOX_ENABLED env var state.

    Returns:
        enabled: bool
        raw_value: str — the raw env value (empty if unset)
    """
    raw = os.environ.get("AIPASS_SANDBOX_ENABLED", "")
    enabled = raw.lower() in ("1", "true", "yes")
    json_handler.log_operation("sandbox_check_flag", {"enabled": enabled, "raw": raw})
    return {"enabled": enabled, "raw_value": raw}


def check_bwrap_present() -> Dict[str, Any]:
    """Check if bubblewrap (bwrap) binary is on PATH.

    Returns:
        found: bool
        path: str | None — resolved path if found
    """
    path = shutil.which("bwrap")
    json_handler.log_operation("sandbox_check_bwrap_present", {"found": bool(path)})
    return {"found": bool(path), "path": path}


def check_bwrap_functional() -> Dict[str, Any]:
    """Run a trivial bwrap sandbox to verify it actually works.

    Catches AppArmor/userns restrictions that make bwrap present but blocked.

    Returns:
        ok: bool
        detail: str — success message or error detail
        sysctl_value: str | None — kernel.apparmor_restrict_unprivileged_userns on failure
    """
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return {"ok": False, "detail": "bwrap not found", "sysctl_value": None}

    try:
        proc = subprocess.run(
            [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "true"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0:
            json_handler.log_operation("sandbox_check_bwrap_functional", {"ok": True})
            return {"ok": True, "detail": "trivial sandbox succeeded", "sysctl_value": None}

        sysctl_val = _read_userns_sysctl()
        detail = f"exit {proc.returncode}"
        if proc.stderr.strip():
            detail = f"{detail}: {proc.stderr.strip()[:200]}"
        json_handler.log_operation("sandbox_check_bwrap_functional", {"ok": False, "detail": detail})
        return {"ok": False, "detail": detail, "sysctl_value": sysctl_val}

    except subprocess.TimeoutExpired:
        logger.warning("[sandbox_check] bwrap functional test timed out")
        return {"ok": False, "detail": "timed out (10s)", "sysctl_value": None}
    except OSError as exc:
        logger.warning("[sandbox_check] bwrap functional test error: %s", exc)
        return {"ok": False, "detail": str(exc), "sysctl_value": None}


def _read_userns_sysctl() -> str | None:
    """Read kernel.apparmor_restrict_unprivileged_userns sysctl if available."""
    try:
        proc = subprocess.run(
            ["sysctl", "-n", "kernel.apparmor_restrict_unprivileged_userns"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.info("[sandbox_check] sysctl read failed (expected on non-Ubuntu): %s", exc)
    return None


def check_node_present() -> Dict[str, Any]:
    """Check if node binary is on PATH.

    Returns:
        found: bool
        path: str | None — resolved path if found
    """
    path = shutil.which("node")
    json_handler.log_operation("sandbox_check_node", {"found": bool(path)})
    return {"found": bool(path), "path": path}


def _find_srt_resolver() -> Path | None:
    """Locate _srt_resolve.mjs inside the sibling aipass.hooks branch.

    Uses importlib.util.find_spec so no absolute/hardcoded path is baked in —
    this works regardless of where the repo is checked out. aipass.hooks is a
    namespace package (no __init__.py required) so find_spec still resolves
    it via submodule_search_locations.

    Returns:
        Path to the resolver script if aipass.hooks is importable and the
        file exists on disk, else None.
    """
    try:
        spec = importlib.util.find_spec("aipass.hooks")
    except (ImportError, ValueError, ModuleNotFoundError) as exc:
        logger.info("[sandbox_check] aipass.hooks not importable: %s", exc)
        return None

    if spec is None or not spec.submodule_search_locations:
        logger.info("[sandbox_check] aipass.hooks package not found")
        return None

    hooks_dir = Path(next(iter(spec.submodule_search_locations)))
    resolver = hooks_dir / "apps" / "modules" / "_srt_resolve.mjs"
    if not resolver.is_file():
        logger.warning("[sandbox_check] srt resolver script missing at %s", resolver)
        return None
    return resolver


def _srt_install_hint() -> str:
    """Build an install hint that names the actual npm global prefix.

    Falls back to the plain install command if npm isn't available or the
    prefix query fails — still a valid hint, just less specific.
    """
    plain = "npm install -g @anthropic-ai/sandbox-runtime"
    npm = shutil.which("npm")
    if not npm:
        return plain

    try:
        proc = subprocess.run(
            [npm, "root", "-g"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        root = proc.stdout.strip()
        if proc.returncode == 0 and root:
            return f"{plain}  (installs to {root})"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.info("[sandbox_check] npm root -g query failed: %s", exc)

    return plain


def check_srt_resolvable() -> Dict[str, Any]:
    """Check if @anthropic-ai/sandbox-runtime is resolvable via node.

    Delegates to _srt_resolve.mjs (owned by the hooks branch) for resolution —
    it tries npm_config_prefix, `npm root -g`, and known global node_modules
    locations in order, which correctly handles layouts where node's own
    install prefix differs from npm's global prefix (Debian/Ubuntu, official
    node Docker images). See DPLAN-0279.

    Returns:
        found: bool
        path: str | None — resolved entry path if found
        install_hint: str — npm install command if missing
    """
    node = shutil.which("node")
    if not node:
        return {
            "found": False,
            "path": None,
            "install_hint": "Install node first, then: npm install -g @anthropic-ai/sandbox-runtime",
        }

    resolver = _find_srt_resolver()
    if resolver is None:
        json_handler.log_operation("sandbox_check_srt", {"found": False})
        return {"found": False, "path": None, "install_hint": _srt_install_hint()}

    try:
        proc = subprocess.run(
            [node, str(resolver), "--resolve"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            path = proc.stdout.strip()
            json_handler.log_operation("sandbox_check_srt", {"found": True, "path": path})
            return {"found": True, "path": path, "install_hint": ""}

        tried = proc.stderr.strip()
        if tried:
            logger.info("[sandbox_check] srt not resolvable, tried:\n%s", tried)

    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("[sandbox_check] srt resolve error: %s", exc)

    json_handler.log_operation("sandbox_check_srt", {"found": False})
    return {
        "found": False,
        "path": None,
        "install_hint": _srt_install_hint(),
    }


def check_rg_present() -> Dict[str, Any]:
    """Check if ripgrep (rg) is available — matches hooks' fallback logic.

    Returns:
        found: bool
        path: str | None — resolved path if found
    """
    rg = shutil.which("rg")
    if rg:
        json_handler.log_operation("sandbox_check_rg", {"found": True, "path": rg})
        return {"found": True, "path": rg}

    fallback = Path.home() / ".local" / "bin" / "rg"
    if fallback.is_file():
        path = str(fallback)
        json_handler.log_operation("sandbox_check_rg", {"found": True, "path": path})
        return {"found": True, "path": path}

    json_handler.log_operation("sandbox_check_rg", {"found": False})
    return {"found": False, "path": None}


def check_broker_alive(repo_root: Path | None = None) -> Dict[str, Any]:
    """Check if the broker daemon socket is accepting connections.

    Args:
        repo_root: Project root containing .ai_central/. Auto-detected if None.

    Returns:
        alive: bool
        detail: str — status message
    """
    sock_path = _find_broker_socket(repo_root)
    if sock_path is None:
        json_handler.log_operation("sandbox_check_broker", {"alive": False, "reason": "socket_not_found"})
        return {"alive": False, "detail": "broker socket not found"}

    if not sock_path.exists():
        json_handler.log_operation("sandbox_check_broker", {"alive": False, "reason": "socket_missing"})
        return {"alive": False, "detail": f"socket missing: {sock_path}"}

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(str(sock_path))
        s.close()
        json_handler.log_operation("sandbox_check_broker", {"alive": True})
        return {"alive": True, "detail": "connected"}
    except (OSError, socket.timeout) as exc:
        logger.info("[sandbox_check] broker connect failed: %s", exc)
        json_handler.log_operation("sandbox_check_broker", {"alive": False, "reason": str(exc)})
        return {"alive": False, "detail": f"connect failed: {exc}"}


def _find_broker_socket(repo_root: Path | None) -> Path | None:
    """Locate the broker socket under $REPO/.ai_central/drone_broker.sock."""
    if repo_root and (repo_root / ".ai_central" / "drone_broker.sock").parent.is_dir():
        return repo_root / ".ai_central" / "drone_broker.sock"

    aipass_home = os.environ.get("AIPASS_HOME", "")
    if aipass_home:
        candidate = Path(aipass_home) / ".ai_central" / "drone_broker.sock"
        if candidate.parent.is_dir():
            return candidate

    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / ".ai_central" / "drone_broker.sock"
        if candidate.parent.is_dir():
            return candidate
        if parent == parent.parent:
            break

    return None


def is_linux() -> bool:
    """Return True if running on Linux."""
    return sys.platform.startswith("linux")
