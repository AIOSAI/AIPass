# =================== AIPass ====================
# Name: setup.py
# Description: Logger Setup & Management
# Version: 1.4.0
# Created: 2025-11-10
# Modified: 2026-10-24
# =============================================

"""PRAX Logger Setup"""

import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Iterator, Optional
from logging.handlers import RotatingFileHandler

try:
    import fcntl
except ImportError:  # Windows: rotation runs unlocked
    fcntl = None  # type: ignore[assignment]

from aipass.prax.apps.handlers.config.load import (
    get_system_logs_dir,
    get_module_logs_dir,
    load_log_config,
    lines_to_bytes,
    level_to_int,
    resolve_log_level,
)

from aipass.prax.apps.handlers.logging.introspection import (
    get_calling_module_path,
    detect_branch_from_path,
    detect_external_project,
)


logger = logging.getLogger(__name__)
_captured_loggers: Dict[str, logging.Logger] = {}
_captured_loggers_lock = threading.Lock()
# Held across a whole logger build, not just the cache read: two racing builds would each
# open handlers on the same files. Re-entrant because a build can log through prax on its own thread.
_logger_build_lock = threading.RLock()


@contextmanager
def rotation_lock(path: Path) -> Iterator[None]:
    """Exclusive cross-process lock on '<path>.lock' while a file rotates; no-op without fcntl."""
    if fcntl is None:
        yield
        return
    with open(f"{path}.lock", "a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        yield


class SafeRotatingFileHandler(RotatingFileHandler):
    """Size rotation shared by every process writing one file.

    Each process rotates on the on-disk size and follows a rename another process made,
    so a rotation is never repeated or written past. Rotation errors (Windows file locks) are skipped."""

    def _follow_rotation(self) -> bool:
        """Reopen the stream if the file on disk is no longer the one it writes to; True if reopened."""
        if self.stream is None:
            return False
        try:
            moved = os.stat(self.baseFilename).st_ino != os.fstat(self.stream.fileno()).st_ino
        except FileNotFoundError:
            moved = True
        if moved:
            self.stream.close()
            self.stream = self._open()
        return moved

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        """Roll when the on-disk file plus this record reaches maxBytes."""
        self._follow_rotation()
        if self.maxBytes <= 0:
            return False
        try:
            size = os.stat(self.baseFilename).st_size
        except OSError:
            return False
        return size + len(f"{self.format(record)}\n") >= self.maxBytes

    def doRollover(self) -> None:
        """Rotate under the cross-process lock, unless another process already did."""
        try:
            with rotation_lock(Path(self.baseFilename)):
                if not self._follow_rotation():
                    super().doRollover()
        except OSError as exc:
            # Windows locks open files, so the rename fails; keep writing to the current file.
            logger.warning("Log rotation skipped (file locked): %s", exc)


def _safe_rotating_handler(log_file: Path, max_bytes: int, backup_count: int) -> logging.Handler:
    """Create RotatingFileHandler — self-heals missing directories, never crashes."""
    try:
        parent = log_file.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        return SafeRotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    except OSError as e:
        logger.error("Log handler failed for %s: %s", log_file, e)
        return logging.NullHandler()


def _tier_handler(resolve_dir: Callable[[], Path], filename: str, max_bytes: int, backup_count: int) -> logging.Handler:
    """Open one tier's file. A log home that cannot be made is a NullHandler, never a raise.

    The resolvers create what they return, so an unwritable home raises from them. A muted
    tier is one "Log handler failed" line at build, then silent until the process restarts.
    """
    try:
        log_dir = resolve_dir()
    except (OSError, RuntimeError) as e:  # RuntimeError: Path.home() with no home to find
        logger.error("Log handler failed for %s: %s", filename, e)
        return logging.NullHandler()
    return _safe_rotating_handler(log_dir / filename, max_bytes, backup_count)


def _made(log_dir: Path) -> Path:
    """Create ``log_dir`` and return it: a resolver for _tier_handler, which guards the mkdir."""
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_individual_logger(
    module_name: str,
    caller_path: Optional[str] = None,
    caller_branch: Optional[str] = None,
) -> logging.Logger:
    """Setup individual logger for a specific module with dual logging support"""
    branch_name: Optional[str] = caller_branch
    resolved_module_path: Optional[str] = caller_path
    if not branch_name:
        resolved_module_path = caller_path or get_calling_module_path()
        branch_path = detect_branch_from_path(resolved_module_path) if resolved_module_path else None
        branch_name = Path(branch_path).name if branch_path else None

    # Set by drone for dispatched commands.
    if not branch_name:
        branch_name = os.environ.get("AIPASS_BRANCH_NAME")

    # Same-named modules of two branches in one process must not share a logger or its files.
    key = f"{branch_name or ''}_{module_name}"
    with _captured_loggers_lock:
        if key in _captured_loggers:
            return _captured_loggers[key]

    with _logger_build_lock:
        # Checked again: the thread that held the build lock may have just built this logger.
        with _captured_loggers_lock:
            if key in _captured_loggers:
                return _captured_loggers[key]
        logger = _build_individual_logger(module_name, resolved_module_path, branch_name)
        with _captured_loggers_lock:
            _captured_loggers[key] = logger
        return logger


def _build_individual_logger(
    module_name: str,
    resolved_module_path: Optional[str],
    branch_name: Optional[str],
) -> logging.Logger:
    """Build one module's logger. Called only under _logger_build_lock."""
    # Outside the getLogger registry, which is keyed by name alone; the line keeps its "captured_<module>" tag.
    logger = logging.Logger(f"captured_{module_name}")
    logger.parent = logging.root

    log_config = load_log_config()

    # The logger's own gate runs before any handler's, so it sits at the more permissive
    # tier level or that tier's records are dropped before its handler sees them.
    system_level = resolve_log_level(log_config["system_logs"].get("log_level"))
    local_level = resolve_log_level(log_config["local_logs"].get("log_level"))
    logger.setLevel(min(level_to_int(system_level), level_to_int(local_level)))

    external_project = None
    if not branch_name:
        check_path = resolved_module_path or os.environ.get("AIPASS_CALLER_CWD")
        if check_path:
            external_project = detect_external_project(check_path)

    if not branch_name and not external_project:
        branch_name = "unknown_branch"

    formatter = logging.Formatter(log_config["log_format"], log_config["date_format"])

    if external_project:
        project_name, project_root = external_project

        system_log_file = f"{project_name}_{module_name}.log"
        system_limits = log_config["system_logs"]
        system_max_bytes = lines_to_bytes(system_limits["max_lines"])
        system_handler = _tier_handler(
            lambda: _made(project_root / "system_logs"),
            system_log_file,
            system_max_bytes,
            system_limits["backup_count"],
        )
        system_handler.setFormatter(formatter)
        system_handler.setLevel(system_level)
        logger.addHandler(system_handler)

        module_log_file = f"{module_name}.log"
        local_limits = log_config["local_logs"]
        local_max_bytes = lines_to_bytes(local_limits["max_lines"])
        local_handler = _tier_handler(
            lambda: _made(project_root / "logs"), module_log_file, local_max_bytes, local_limits["backup_count"]
        )
        local_handler.setFormatter(formatter)
        local_handler.setLevel(local_level)
        logger.addHandler(local_handler)

    else:
        system_log_file = f"{branch_name}_{module_name}.log"
        system_limits = log_config["system_logs"]
        system_max_bytes = lines_to_bytes(system_limits["max_lines"])
        system_handler = _tier_handler(
            get_system_logs_dir, system_log_file, system_max_bytes, system_limits["backup_count"]
        )
        system_handler.setFormatter(formatter)
        system_handler.setLevel(system_level)
        logger.addHandler(system_handler)

        module_log_file = f"{module_name}.log"
        local_limits = log_config["local_logs"]
        local_max_bytes = lines_to_bytes(local_limits["max_lines"])
        local_handler = _tier_handler(
            lambda: get_module_logs_dir(branch_name), module_log_file, local_max_bytes, local_limits["backup_count"]
        )
        local_handler.setFormatter(formatter)
        local_handler.setLevel(local_level)
        logger.addHandler(local_handler)

    return logger


def get_captured_loggers_count() -> int:
    """Get count of captured loggers"""
    return len(_captured_loggers)
