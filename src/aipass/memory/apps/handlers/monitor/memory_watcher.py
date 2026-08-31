# =================== AIPass ====================
# Name: memory_watcher.py
# Description: Memory File System Watcher
# Version: 1.1.0
# Created: 2025-11-26
# Modified: 2026-03-06
# =============================================

"""
Memory File System Watcher

Watches memory files (*.local.json, *.observations.json) for modifications.
On change, updates line counts and triggers rollover if needed.

Purpose:
    Automatic memory file monitoring without polling. Responds to filesystem
    events in real-time, keeping metadata accurate and triggering rollover
    when thresholds are exceeded.

Independence:
    Uses watchdog library for events. Delegates to line_counter and rollover
    handlers for processing. No direct service dependencies.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any

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

# Handler imports (relative within package — after conditional watchdog block)
from aipass.memory.apps.handlers.tracking.line_counter import update_line_count  # noqa: E402
from aipass.memory.apps.handlers.monitor.detector import check_single_file  # noqa: E402
from aipass.memory.apps.handlers import repo_root
from aipass.memory.apps.handlers.repo_root import exactly_named, exists_exactly  # noqa: E402
from aipass.prax.apps.modules.logger import get_system_logger  # noqa: E402
from aipass.memory.apps.handlers.json import json_handler  # noqa: E402
from aipass.memory.apps.handlers.json import config_loader  # noqa: E402

logger = get_system_logger()

# Memory root resolved relative to handler location
_MEMORY_ROOT = Path(__file__).resolve().parents[3]

# Global observer instance
_observer: Any = None


# =============================================================================
# STARTUP CHECK (runs once per command, no daemon needed)
# =============================================================================

_startup_check_done = False


def _check_vector_deps() -> bool:
    """
    Check whether the memory venv has chromadb and numpy available.

    Runs a quick subprocess check using the memory venv Python.
    Logs a warning if deps are missing so the self-report is honest.

    Returns:
        True if both chromadb and numpy are importable, False otherwise
    """
    import subprocess
    import sys

    venv_python = _MEMORY_ROOT / ".venv" / "bin" / "python3"
    if not venv_python.exists():
        venv_python = Path(sys.executable)

    try:
        result = subprocess.run(
            [str(venv_python), "-c", "import chromadb; import numpy"],
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
    """
    Check all memory files and trigger rollover if any exceed their threshold.
    Also processes any new files in memory_pool.

    Threshold is determined per-branch from v2 entry-count limits in config.

    This is a startup check - runs once per command, synchronous.
    No daemon or file watcher needed.

    Returns:
        Dict with check results and any rollover actions taken
    """
    global _startup_check_done

    # Only run once per process
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

    # Get all branch paths
    branch_paths = _get_branch_paths()

    if not branch_paths:
        results["error"] = "No branch paths found"
        return results

    # Check each branch for memory files over limit
    for branch_path in branch_paths:
        branch = Path(branch_path)
        # Find memory files in .trinity/ subdirectory
        trinity_dir = branch / ".trinity"
        if not trinity_dir.exists():
            continue
        for pattern in ["local.json", "observations.json"]:
            # Not glob(): the pattern has no wildcard, and a folding filesystem
            # would serve Local.json here. Rollover REWRITES what this matches,
            # so a near-miss is damage rather than a miscount.
            for memory_file in [trinity_dir / pattern] if exists_exactly(trinity_dir / pattern) else []:
                results["files_checked"] += 1

                try:
                    # Auto-heal: reconcile file against template (strips orphan keys)
                    from aipass.memory.apps.handlers.schema.normalize import normalize_memory_file

                    normalize_memory_file(memory_file)

                    # Use detector for trigger decision (v2 entry-count based)
                    from aipass.memory.apps.handlers.monitor.detector import _should_rollover

                    triggered, current_lines, _, _ = _should_rollover(memory_file)
                    if triggered:
                        results["files_over_limit"].append(
                            {"file": str(memory_file), "lines": current_lines, "threshold": 0}
                        )
                except Exception as e:
                    logger.warning(f"[memory_watcher] Failed to read memory file {memory_file}: {e}")

    results["lines_synced"] = 0

    # Trigger rollover if any files are over limit
    if results["files_over_limit"]:
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

    # Check memory_pool for new files to process
    results["memory_pool"] = _check_memory_pool()

    # Check plans for new files to vectorize
    results["plans"] = _check_plans()

    # Check code_archive for new files to index
    results["code_archive"] = _check_code_archive()

    json_handler.log_operation(
        "check_and_rollover",
        {
            "files_checked": results.get("files_checked", 0),
            "rollover_triggered": results.get("rollover_triggered", False),
        },
    )

    return results


def _check_memory_pool() -> Dict[str, Any]:
    """
    Check memory_pool for new files and process if needed.

    Compares files in pool against configured keep_recent limit.
    If more files exist, runs processor to vectorize and archive.

    Returns:
        Dict with processing status
    """
    pool_config = config_loader.section("memory_pool")
    pool_path = _MEMORY_ROOT / "memory_pool"

    # Check if enabled
    if not pool_config.get("enabled", False):
        return {"success": True, "skipped": True, "reason": "memory_pool disabled"}

    # Count files in pool (excluding .archive)
    extensions = pool_config.get("supported_extensions", [".md", ".txt"])
    keep_recent = pool_config.get("keep_recent", 0)

    files = []
    for ext in extensions:
        files.extend(pool_path.glob(f"*{ext}"))

    file_count = len(files)

    # If under limit, nothing to do
    if file_count <= keep_recent:
        return {"success": True, "files_in_pool": file_count, "keep_recent": keep_recent, "action": "none"}

    # Files exceed limit - run processor
    try:
        # NOTE: intake module not yet ported to aipass.memory package
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
    """
    Check plans directory for unprocessed files (count only).

    Does NOT call process_plans() — that spawns heavy ML subprocesses.
    Only counts pending files and reports. Use 'drone @memory process-plans'
    to trigger actual vectorization.

    Returns:
        Dict with pending file count
    """
    import json

    plans_config = config_loader.section("plans")

    # Check if enabled
    if not plans_config.get("enabled", False):
        return {"success": True, "skipped": True, "reason": "plans disabled"}

    # Get plans path and count files (supports absolute paths)
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

    # Load manifest to count unprocessed files
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


def _check_code_archive() -> Dict[str, Any]:
    """
    Check code_archive for new files and index them.

    Returns:
        Dict with indexing status
    """
    try:
        from aipass.memory.apps.handlers.archive.indexer import check_for_new_files

        return check_for_new_files()
    except Exception as e:
        logger.warning(f"[memory_watcher] Code archive check failed: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def _find_repo_root() -> Path:
    """Repo root for this lane — resolved by ``handlers/repo_root.py``.

    Kept as a local name because callers and tests patch it here. The body is a
    delegation on purpose: this function used to be one of ten byte-identical
    copies, so the first cure landed on one file and CI went red on the next.

    Returns:
        The directory holding AIPASS_REGISTRY.json, or the source tree. Never
        the process working directory.
    """
    return repo_root.find_repo_root(caller="memory_watcher")


def _paths_from_registry(registry_path: Path, root: Path) -> list[Path]:
    """Read branch paths from a single registry file."""
    import json

    if not registry_path.exists():
        return []

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            branches = data.get("branches", [])

            paths = []
            for branch in branches:
                raw_path = branch.get("path", "")
                branch_path = Path(raw_path)
                if not branch_path.is_absolute():
                    branch_path = root / raw_path
                if branch_path.exists():
                    paths.append(branch_path)

            return paths
    except Exception as e:
        logger.warning(f"[memory_watcher] Failed to read registry {registry_path}: {e}")
        return []


def _get_branch_paths() -> list[Path]:
    """
    Get all branch paths from AIPass registry + external project registries.

    Reads persisted known_registries.json AND does the cwd walk so
    external-project branches are always reachable regardless of caller cwd.

    Returns:
        List of Path objects for each branch
    """
    import os

    from aipass.memory.apps.handlers.monitor.detector import load_known_registries, persist_registry

    repo_root = _find_repo_root()
    paths = _paths_from_registry(repo_root / "AIPASS_REGISTRY.json", repo_root)
    seen = {p.resolve() for p in paths}
    aipass_registry = (repo_root / "AIPASS_REGISTRY.json").resolve()

    def _add_from_registry(reg: Path) -> None:
        for p in _paths_from_registry(reg, reg.parent):
            if p.resolve() not in seen:
                paths.append(p)
                seen.add(p.resolve())

    for reg in load_known_registries():
        if reg.resolve() != aipass_registry:
            _add_from_registry(reg)

    caller_cwd = (
        Path(os.environ.get("AIPASS_CALLER_CWD", "")).resolve() if os.environ.get("AIPASS_CALLER_CWD") else Path.cwd()
    )

    cwd_found: list[Path] = []
    for parent in [caller_cwd] + list(caller_cwd.parents):
        # EXACT CASE -- detector's twin of this walk, and the consequence here
        # is that a folded match's "branches" become paths this watcher ROLLS
        # OVER, i.e. rewrites. See repo_root.exactly_named.
        for reg in exactly_named(sorted(parent.glob("*_REGISTRY.json")), "_REGISTRY.json"):
            if reg.resolve() != aipass_registry:
                cwd_found.append(reg)
        if cwd_found:
            break

    for reg in cwd_found:
        _add_from_registry(reg)
        persist_registry(reg)

    return paths


def _is_memory_file(file_path: Path) -> bool:
    """
    Check if file is a memory file in .trinity/ (local.json or observations.json)

    Args:
        file_path: Path to check

    Returns:
        True if memory file, False otherwise
    """
    name = file_path.name
    parent = file_path.parent.name
    return parent == ".trinity" and name in ("local.json", "observations.json")


# =============================================================================
# FILE SYSTEM EVENT HANDLER
# =============================================================================


class MemoryFileWatcher(FileSystemEventHandler):  # type: ignore[misc]
    """Watch for memory file modifications"""

    def __init__(self):
        super().__init__()
        # Track recent modifications to avoid duplicate processing
        self._recent_modifications = set()

    def on_modified(self, event):
        """Handle file modification events"""
        # Ignore directory events
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Only process memory files
        if not _is_memory_file(file_path):
            return

        # Skip if we just processed this file
        file_key = str(file_path)
        if file_key in self._recent_modifications:
            self._recent_modifications.discard(file_key)
            return

        logger.info(f"[memory_watcher] Detected modification: {file_path.name}")

        # Step 1: Auto-heal schema drift (strips orphan keys)
        from aipass.memory.apps.handlers.schema.normalize import normalize_memory_file

        norm_result = normalize_memory_file(file_path)
        if norm_result.get("changes"):
            self._recent_modifications.add(file_key)

        # Step 2: Update health check metadata
        update_result = update_line_count(file_path)

        if not update_result["success"]:
            logger.error(
                f"[memory_watcher] Failed to update metadata for {file_path.name}: {update_result.get('error')}"
            )
            return

        # Step 3: Check if rollover needed
        check_result = check_single_file(file_path)

        if not check_result["success"]:
            logger.error(f"[memory_watcher] Failed to check rollover for {file_path.name}: {check_result.get('error')}")
            return

        if check_result.get("should_rollover", False):
            trigger = check_result.get("trigger")
            logger.warning(f"[memory_watcher] ROLLOVER TRIGGERED: {trigger}")

            # Import rollover handler here to avoid circular imports
            from aipass.memory.apps.handlers.rollover.orchestrator import execute_rollover

            # Trigger rollover
            logger.info(f"[memory_watcher] Triggering rollover for {file_path.name}")

            # Mark file as recently modified to avoid re-processing after rollover
            self._recent_modifications.add(file_key)

            # Execute rollover
            try:
                execute_rollover()
            except Exception as e:
                logger.error(f"[memory_watcher] Rollover failed: {e}")


# =============================================================================
# WATCHER CONTROL FUNCTIONS
# =============================================================================


def start_memory_watcher() -> Dict[str, Any]:
    """
    Start watching memory files for modifications

    Starts watchdog observer to monitor all branch directories for memory
    file changes. Updates line counts and triggers rollover automatically.

    Returns:
        Dict with success status and watched paths
    """
    global _observer

    if _observer and _observer.is_alive():
        return {"success": False, "error": "Watcher already running"}

    # Get all branch paths
    branch_paths = _get_branch_paths()

    if not branch_paths:
        return {"success": False, "error": "No branch paths found in AIPASS_REGISTRY.json"}

    # Create watcher instance
    watcher = MemoryFileWatcher()

    # Create observer
    new_observer = Observer()  # type: ignore[misc]

    # Schedule watcher for each branch path (silent - no logging during startup)
    watched_paths = []
    for branch_path in branch_paths:
        try:
            new_observer.schedule(watcher, str(branch_path), recursive=True)
            watched_paths.append(str(branch_path))
        except Exception as e:
            logger.warning(f"[memory_watcher] Failed to schedule watcher for {branch_path}: {e}")

    # Start observer
    new_observer.start()
    _observer = new_observer

    return {"success": True, "watched_paths": watched_paths, "count": len(watched_paths)}


def stop_memory_watcher() -> Dict[str, Any]:
    """
    Stop the memory file watcher

    Returns:
        Dict with success status
    """
    global _observer

    if not _observer or not _observer.is_alive():
        return {"success": False, "error": "Watcher not running"}

    _observer.stop()
    _observer.join()
    _observer = None

    logger.info("[memory_watcher] Stopped")

    return {"success": True, "message": "Memory watcher stopped"}


def is_memory_watcher_active() -> bool:
    """
    Check if memory watcher is currently active

    Returns:
        True if watcher is running, False otherwise
    """
    return _observer is not None and _observer.is_alive()


def get_watcher_status() -> Dict[str, Any]:
    """
    Get current watcher status

    Returns:
        Dict with watcher status and details
    """
    active = is_memory_watcher_active()

    if not active:
        return {"active": False, "message": "Watcher not running"}

    # Get watched paths
    branch_paths = _get_branch_paths()

    return {"active": True, "watched_directories": len(branch_paths), "paths": [str(p) for p in branch_paths]}


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(description="Memory File Watcher - Monitor memory files for rollover")
    parser.add_argument("command", choices=["start", "stop", "status"], help="Command to execute")

    args = parser.parse_args()

    if args.command == "start":
        result = start_memory_watcher()

        if result["success"]:
            print(f"Started watching {result['count']} directories")
            print("Press Ctrl+C to stop...")

            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("[memory_watcher] Watcher stopped by user (KeyboardInterrupt)")
                print("\nStopping...")
                stop_memory_watcher()
        else:
            print(f"Failed to start: {result.get('error')}")

    elif args.command == "stop":
        result = stop_memory_watcher()

        if result["success"]:
            print(result["message"])
        else:
            print(f"Failed to stop: {result.get('error')}")

    elif args.command == "status":
        status = get_watcher_status()

        if status["active"]:
            print("Watcher is ACTIVE")
            print(f"Watching {status['watched_directories']} directories:")
            for path in status["paths"]:
                print(f"  - {path}")
        else:
            print("Watcher is INACTIVE")
