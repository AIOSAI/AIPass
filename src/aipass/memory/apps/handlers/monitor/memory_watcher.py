# =================== AIPass ====================
# Name: memory_watcher.py
# Description: Memory File System Watcher
# Version: 1.2.3
# Created: 2025-11-26
# Modified: 2026-10-17
# =============================================

"""
Memory File System Watcher

Uses watchdog when present; delegates to the detector and the rollover orchestrator.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any, Iterable

if TYPE_CHECKING:
    pass

# Temporary logger for module-level import guards (overwritten below by get_system_logger)
logger = logging.getLogger(__name__)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object  # type: ignore[assignment,misc]
    logger.info("Optional dependency 'watchdog' not available")

from aipass.memory.apps.handlers.monitor.detector import RegistryUnreadable, check_single_file
from aipass.memory.apps.handlers import repo_root
from aipass.memory.apps.handlers.repo_root import exists_exactly
from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.repo_root import module_file
from aipass.memory.apps.handlers.storage.lane import memory_python

logger = get_system_logger()

_MEMORY_ROOT = module_file(__file__).parents[3]

_observer: Any = None


_startup_check_done = False


def _check_vector_deps() -> bool:
    """Check whether the memory venv has chromadb and numpy available."""
    import subprocess

    try:
        result = subprocess.run(
            [memory_python(), "-c", "import chromadb; import numpy"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning(
                "[memory_watcher] vector storage degraded — chromadb/numpy not available in memory venv. "
                "Run: pip install -e '.[dev,memory]'"
            )
            return False
        return True
    except Exception as e:
        logger.warning(f"[memory_watcher] vector dep check failed: {e}")
        return False


def check_and_rollover() -> Dict[str, Any]:
    """Check all memory files and trigger rollover if any exceed their threshold; once per process."""
    global _startup_check_done

    if _startup_check_done:
        return {"success": True, "skipped": True, "reason": "Already checked this session"}

    _startup_check_done = True

    vector_deps_ok = _check_vector_deps()

    results = {
        "success": True,
        "files_checked": 0,
        "files_over_limit": [],
        "rollover_triggered": False,
        "memory_pool": None,
        "vector_storage": "healthy" if vector_deps_ok else "degraded — chromadb/numpy not installed",
    }

    try:
        branch_paths = _get_branch_paths()
    except RegistryUnreadable as e:
        logger.error(f"[memory_watcher] {e}")
        results["success"] = False
        results["error"] = str(e)
        return results

    if not branch_paths:
        results["error"] = "No branch paths found"
        return results

    for branch_path in branch_paths:
        branch = Path(branch_path)
        trinity_dir = branch / ".trinity"
        if not trinity_dir.exists():
            continue
        for pattern in ["local.json", "observations.json"]:
            # Not glob(): a folding filesystem would serve Local.json, and rollover rewrites what matches.
            for memory_file in [trinity_dir / pattern] if exists_exactly(trinity_dir / pattern) else []:
                results["files_checked"] += 1

                try:
                    # Auto-heal: reconcile file against template (strips orphan keys)
                    from aipass.memory.apps.handlers.schema.normalize import normalize_memory_file

                    normalize_memory_file(memory_file)

                    from aipass.memory.apps.handlers.monitor.detector import _should_rollover

                    triggered, current_lines, _, _ = _should_rollover(memory_file)
                    if triggered:
                        results["files_over_limit"].append(
                            {"file": str(memory_file), "lines": current_lines, "threshold": 0}
                        )
                except Exception as e:
                    logger.warning(f"[memory_watcher] Failed to read memory file {memory_file}: {e}")

    results["lines_synced"] = 0

    if results["files_over_limit"] and not vector_deps_ok:
        logger.warning("[memory_watcher] Rollover skipped: vector storage degraded, the files keep their entries")
        results["rollover_skipped"] = "vector storage degraded"
    elif results["files_over_limit"]:
        results["rollover_triggered"] = True

        try:
            from aipass.memory.apps.handlers.rollover.orchestrator import execute_rollover

            execute_rollover()
        except ImportError:
            logger.warning("Rollover handler not available")
        except Exception as e:
            logger.error(f"[memory_watcher] Rollover execution failed: {e}")
            results["rollover_error"] = str(e)
            results["success"] = False

    results["memory_pool"] = _check_memory_pool()

    results["plans"] = _check_plans()

    json_handler.log_operation(
        "check_and_rollover",
        {
            "files_checked": results.get("files_checked", 0),
            "rollover_triggered": results.get("rollover_triggered", False),
        },
    )

    return results


def _check_memory_pool() -> Dict[str, Any]:
    """Process memory_pool when it holds more files than keep_recent."""
    pool_config = config_loader.section("memory_pool")
    pool_path = _MEMORY_ROOT / "memory_pool"

    if not pool_config.get("enabled", False):
        return {"success": True, "skipped": True, "reason": "memory_pool disabled"}

    extensions = pool_config.get("supported_extensions", [".md", ".txt"])
    keep_recent = pool_config.get("keep_recent", 0)

    files = []
    for ext in extensions:
        files.extend(pool_path.glob(f"*{ext}"))

    file_count = len(files)

    if file_count <= keep_recent:
        return {"success": True, "files_in_pool": file_count, "keep_recent": keep_recent, "action": "none"}

    try:
        from aipass.memory.apps.handlers.intake.pool_processor import process_memory_pool  # type: ignore[import-not-found]

        result = process_memory_pool()
        return {
            "success": result.get("success", False),
            "files_processed": result.get("files_processed", 0),
            "files_archived": result.get("archive", {}).get("archived_count", 0),
            "action": "processed",
        }
    except Exception as e:
        logger.warning(f"[memory_watcher] Memory pool processing failed: {e}")
        return {"success": False, "error": str(e), "action": "failed"}


def _check_plans() -> Dict[str, Any]:
    """Count unprocessed plans only: process_plans() spawns heavy ML subprocesses."""
    import json

    plans_config = config_loader.section("plans")

    if not plans_config.get("enabled", False):
        return {"success": True, "skipped": True, "reason": "plans disabled"}

    plans_dir = plans_config.get("path", ".backup/processed_plans")
    repo_root = _find_repo_root()
    plans_path = Path(plans_dir) if Path(plans_dir).is_absolute() else repo_root / plans_dir
    extensions = plans_config.get("supported_extensions", [".md"])

    if not plans_path.exists():
        return {"success": True, "skipped": True, "reason": "plans directory does not exist"}

    files = []
    for ext in extensions:
        files.extend(plans_path.glob(f"*{ext}"))

    file_count = len(files)

    if file_count == 0:
        return {"success": True, "pending_files": 0, "action": "count_only"}

    manifest_path = _MEMORY_ROOT / "memory_json" / ".plans_processed.json"
    manifest: Dict[str, str] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[memory_watcher] Failed to read plans manifest: {e}")

    pending = [f for f in files if f.name not in manifest]
    pending_count = len(pending)

    if pending_count > 0:
        logger.info(f"[plans] {pending_count} plans pending vectorization. Run: drone @memory process-plans")

    return {"success": True, "pending_files": pending_count, "action": "count_only"}


def _find_repo_root() -> Path:
    """Repo root for this lane, by ``handlers/repo_root.py``; a local name because tests patch it here."""
    return repo_root.find_repo_root(caller="memory_watcher")


def _get_branch_paths() -> list[Path]:
    """Branch paths the watcher may roll over: ``detector._read_registry()``, one fleet, nothing else."""
    from aipass.memory.apps.handlers.monitor import detector

    paths: list[Path] = []
    seen: set[Path] = set()
    for branch in detector._read_registry():
        branch_path = Path(branch.get("path", ""))
        if branch.get("path") and branch_path.exists() and branch_path.resolve() not in seen:
            paths.append(branch_path)
            seen.add(branch_path.resolve())

    return paths


def _is_memory_file(file_path: Path, roots: frozenset[Path]) -> bool:
    """
    Check if file is a memory file of a watched root: ``<root>/.trinity/<name>``

    Nothing deeper: copies under a recursive root's dropbox/ or .archive/ are sandboxes, never rewritten.
    """
    trinity = file_path.parent
    return (
        trinity.name == ".trinity" and trinity.parent in roots and file_path.name in ("local.json", "observations.json")
    )


class MemoryFileWatcher(FileSystemEventHandler):  # type: ignore[misc]
    """Watch for memory file modifications of the roots it is handed"""

    def __init__(self, roots: Iterable[Path]):
        super().__init__()
        # Each root in both spellings: an observer may report the real path behind a symlinked root.
        given = [Path(root) for root in roots]
        self._roots = frozenset(given) | frozenset(root.resolve() for root in given)
        self._recent_modifications = set()

    def on_modified(self, event):
        """Handle file modification events"""
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        if not _is_memory_file(file_path, self._roots):
            return

        file_key = str(file_path)
        if file_key in self._recent_modifications:
            self._recent_modifications.discard(file_key)
            return

        logger.info(f"[memory_watcher] Detected modification: {file_path.name}")

        from aipass.memory.apps.handlers.schema.normalize import normalize_memory_file

        norm_result = normalize_memory_file(file_path)
        if norm_result.get("changes"):
            self._recent_modifications.add(file_key)

        check_result = check_single_file(file_path)

        if not check_result["success"]:
            logger.error(f"[memory_watcher] Failed to check rollover for {file_path.name}: {check_result.get('error')}")
            return

        if check_result.get("should_rollover", False):
            trigger = check_result.get("trigger")
            logger.warning(f"[memory_watcher] ROLLOVER TRIGGERED: {trigger}")

            # Imported here to avoid a circular import.
            from aipass.memory.apps.handlers.rollover.orchestrator import execute_rollover

            logger.info(f"[memory_watcher] Triggering rollover for {file_path.name}")

            # Marked before the rollover so its own write is not re-processed.
            self._recent_modifications.add(file_key)

            try:
                execute_rollover()
            except Exception as e:
                logger.error(f"[memory_watcher] Rollover failed: {e}")


def start_memory_watcher() -> Dict[str, Any]:
    """Start the watchdog observer over every branch directory."""
    global _observer

    if _observer and _observer.is_alive():
        return {"success": False, "error": "Watcher already running"}

    try:
        branch_paths = _get_branch_paths()
    except RegistryUnreadable as e:
        logger.error(f"[memory_watcher] Not started: {e}")
        return {"success": False, "error": str(e)}

    if not branch_paths:
        return {"success": False, "error": "No branch paths found in AIPASS_REGISTRY.json"}

    watcher = MemoryFileWatcher(branch_paths)

    new_observer = Observer()  # type: ignore[misc]

    # Silent: no logging during startup.
    watched_paths = []
    for branch_path in branch_paths:
        try:
            new_observer.schedule(watcher, str(branch_path), recursive=True)
            watched_paths.append(str(branch_path))
        except Exception as e:
            logger.warning(f"[memory_watcher] Failed to schedule watcher for {branch_path}: {e}")

    new_observer.start()
    _observer = new_observer

    return {"success": True, "watched_paths": watched_paths, "count": len(watched_paths)}


def stop_memory_watcher() -> Dict[str, Any]:
    """Stop the memory file watcher"""
    global _observer

    if not _observer or not _observer.is_alive():
        return {"success": False, "error": "Watcher not running"}

    _observer.stop()
    _observer.join()
    _observer = None

    logger.info("[memory_watcher] Stopped")

    return {"success": True, "message": "Memory watcher stopped"}


def is_memory_watcher_active() -> bool:
    """Check if memory watcher is currently active"""
    return _observer is not None and _observer.is_alive()


def get_watcher_status() -> Dict[str, Any]:
    """Get current watcher status"""
    active = is_memory_watcher_active()

    if not active:
        return {"active": False, "message": "Watcher not running"}

    try:
        branch_paths = _get_branch_paths()
    except RegistryUnreadable as e:
        # The observer runs; what it watches cannot be listed.
        logger.error(f"[memory_watcher] {e}")
        return {"active": True, "error": str(e)}

    return {"active": True, "watched_directories": len(branch_paths), "paths": [str(p) for p in branch_paths]}
