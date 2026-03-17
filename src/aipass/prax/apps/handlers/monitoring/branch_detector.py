# =================== AIPass ====================
# Name: branch_detector.py
# Description: Branch Attribution Handler
# Version: 0.1.0
# Created: 2025-11-23
# Modified: 2026-03-09
# =============================================

"""
Branch Detection Handler

Detects which branch owns an event by analyzing:
- File paths
- Log filenames
- Module names

Uses BRANCH_REGISTRY.json for accurate mapping with caching for performance.
"""

from pathlib import Path
from typing import Optional, Dict, Set
import json
import logging
from functools import lru_cache

from aipass.prax import logger
from aipass.prax.apps.handlers.json import json_handler

# logger imported from aipass.prax


class BranchDetector:
    """
    Detects branch ownership for files, logs, and modules.

    Uses multiple strategies:
    1. Direct path lookup from BRANCH_REGISTRY.json
    2. Parent directory traversal
    3. Filename pattern matching
    4. Caching for repeated lookups
    """

    def __init__(self):
        """Initialize detector with empty caches"""
        self.branch_map: Dict[str, str] = {}  # path -> branch
        self.log_map: Dict[str, str] = {}     # log file -> branch
        self.module_map: Dict[str, str] = {}  # module -> branch
        self.known_branches: Set[str] = set()
        self._repo_root: Optional[Path] = None
        self._load_registry()
        json_handler.log_operation("branch_detected", {"known_branches": len(self.known_branches)})

    def _find_repo_root(self) -> Path:
        """Walk up from this file to find repo root (contains AIPASS_REGISTRY.json)."""
        if self._repo_root is not None:
            return self._repo_root
        current = Path(__file__).resolve().parent
        for parent in [current] + list(current.parents):
            if (parent / "AIPASS_REGISTRY.json").exists():
                self._repo_root = parent
                return parent
        self._repo_root = Path.cwd()
        return self._repo_root

    def _load_registry(self):
        """
        Load BRANCH_REGISTRY.json and build lookup tables.

        Builds:
        - branch_map: Full path to branch name mapping
        - known_branches: Set of all branch names for pattern matching
        """
        try:
            registry_path = self._find_repo_root() / "AIPASS_REGISTRY.json"

            if not registry_path.exists():
                logger.warning(f"Registry not found: {registry_path}")
                self._load_fallback_branches()
                return

            with open(registry_path, encoding='utf-8') as f:
                data = json.load(f)

                branches = data.get('branches', [])
                if not branches:
                    logger.warning("No branches found in registry")
                    self._load_fallback_branches()
                    return

                for branch in branches:
                    branch_name = branch.get('name', '').upper()
                    branch_path = branch.get('path', '')

                    if not branch_name or not branch_path:
                        continue

                    # Store normalized path
                    path = Path(branch_path).resolve()
                    self.branch_map[str(path)] = branch_name
                    self.known_branches.add(branch_name)

                    # Also store with trailing slash for matching
                    self.branch_map[str(path) + '/'] = branch_name

                logger.info(f"Loaded {len(self.known_branches)} branches from registry")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in registry: {e}")
            self._load_fallback_branches()
        except Exception as e:
            logger.error(f"Error loading registry: {e}")
            self._load_fallback_branches()

    def _load_fallback_branches(self):
        """Load fallback branch names when registry is unavailable"""
        fallback = ['SEED', 'CLI', 'FLOW', 'PRAX', 'CORTEX', 'DRONE',
                   'BACKUP_SYSTEM', 'SECURITY', 'AIPASS']
        self.known_branches.update(fallback)
        logger.info(f"Using fallback branches: {fallback}")

    def detect_from_path(self, file_path: str) -> str:
        """
        Detect branch from file path.

        Strategy:
        1. Check exact path match in branch_map
        2. Walk up parent directories for match
        3. Parse path for known branch names
        4. Return 'UNKNOWN' if no match found

        Args:
            file_path: Absolute or relative file path

        Returns:
            Branch name in uppercase (e.g., 'SEED', 'PRAX')
        """
        try:
            path = Path(file_path).resolve()
            path_str = str(path)

            # Check cache first
            if path_str in self.log_map:
                return self.log_map[path_str]

            # Strategy 1: Exact match
            if path_str in self.branch_map:
                result = self.branch_map[path_str]
                self.log_map[path_str] = result
                return result

            # Strategy 2: Walk up parents
            for parent in path.parents:
                parent_str = str(parent)
                if parent_str in self.branch_map:
                    result = self.branch_map[parent_str]
                    self.log_map[path_str] = result
                    return result

            # Strategy 3: Claude Code project files
            # Path: ~/.claude/projects/-home-aipass-aipass-core-trigger/session.jsonl
            # Folder name encodes the project path with - replacing /
            if '.claude/projects/' in path_str:
                projects_idx = path_str.index('.claude/projects/') + len('.claude/projects/')
                remaining = path_str[projects_idx:]
                # Get the project folder name (first path segment after projects/)
                project_folder = remaining.split('/')[0]
                # Convert folder name back to path: -home-user-src-aipass-trigger -> /home/user/src/aipass/trigger
                project_path = '/' + project_folder.replace('-', '/')
                # Check against branch_map (registered branch paths)
                for registered_path, branch_name in self.branch_map.items():
                    # Normalize for comparison: underscores vs hyphens
                    registered_normalized = registered_path.replace('_', '/')
                    project_normalized = project_path.replace('_', '/')
                    if registered_normalized == project_normalized or registered_path == project_path:
                        self.log_map[path_str] = branch_name
                        return branch_name
                # Fallback: extract last segment as branch name
                segments = [s for s in project_folder.split('-') if s]
                # Try matching from end (last meaningful segment)
                if segments:
                    last = segments[-1].upper()
                    # Check for compound names by trying progressively longer matches from end
                    for i in range(len(segments) - 1, 0, -1):
                        candidate = '_'.join(segments[i:]).upper()
                        if candidate in self.known_branches:
                            self.log_map[path_str] = candidate
                            return candidate
                    if last in self.known_branches:
                        self.log_map[path_str] = last
                        return last

            # Strategy 4: AI_CENTRAL files - {BRANCH}.central.json or {BRANCH}_central.json
            # Path: .../AI_CENTRAL/AI_MAIL.central.json -> AI_MAIL
            if 'AI_CENTRAL' in path_str or '.ai_central' in path_str or 'ai_central' in path_str.lower():
                name = path.name
                # Extract branch from filename patterns
                branch_candidate = None
                if '.central.json' in name:
                    branch_candidate = name.replace('.central.json', '').upper()
                elif '_central.json' in name:
                    branch_candidate = name.replace('_central.json', '').upper()
                if branch_candidate:
                    self.log_map[path_str] = branch_candidate
                    return branch_candidate

            # Strategy 5: Root-level system files (repo root or .claude under it)
            repo_root = self._find_repo_root()
            if path.parent == repo_root or path.parent == repo_root / '.claude':
                self.log_map[path_str] = 'SYSTEM'
                return 'SYSTEM'

            # Strategy 6: Parse path for known branch names
            path_parts = path_str.lower().split('/')
            for part in path_parts:
                branch_upper = part.upper()
                if branch_upper in self.known_branches:
                    self.log_map[path_str] = branch_upper
                    return branch_upper

            # Strategy 6: Check for compound names (e.g., ai_mail -> check for AI_MAIL patterns)
            for part in path_parts:
                if '_' in part:
                    subparts = part.split('_')
                    for subpart in subparts:
                        branch_upper = subpart.upper()
                        if branch_upper in self.known_branches:
                            self.log_map[path_str] = branch_upper
                            return branch_upper

            # No match found
            logger.info(f"Could not detect branch for path: {file_path}")
            return 'UNKNOWN'

        except Exception as e:
            logger.error(f"Error detecting branch from path {file_path}: {e}")
            return 'UNKNOWN'

    def detect_from_log(self, log_file: str) -> str:
        """
        Detect branch from log filename.

        Supports patterns:
        - seed_audit.log -> SEED
        - seed_standards_checklist.log -> SEED
        - flow_plan.log -> FLOW
        - prax_monitor_20251123.log -> PRAX

        Args:
            log_file: Log filename or path

        Returns:
            Branch name in uppercase
        """
        try:
            # Get just the filename
            name = Path(log_file).stem

            # Check cache
            if name in self.log_map:
                return self.log_map[name]

            # Check known branches first (longest match wins)
            # Handles compound names like ai_mail, backup_system, memory_bank
            for branch_name in sorted(self.known_branches, key=len, reverse=True):
                prefix = branch_name.lower() + '_'
                if name.lower().startswith(prefix) or name.lower() == branch_name.lower():
                    self.log_map[name] = branch_name
                    return branch_name

            # Fallback: split on underscore for branches not in registry
            # Log files follow pattern: branch_operation.log
            if '_' in name:
                parts = name.split('_')
                first_part = parts[0].upper()
                self.log_map[name] = first_part
                return first_part

            # Try full name (no underscore)
            name_upper = name.upper()
            if name_upper in self.known_branches:
                self.log_map[name] = name_upper
                return name_upper

            # If we have a full path, try path detection
            if '/' in log_file:
                return self.detect_from_path(log_file)

            logger.info(f"Could not detect branch from log: {log_file}")
            return 'UNKNOWN'

        except Exception as e:
            logger.info(f"Error detecting branch from log {log_file}: {e}")
            return 'UNKNOWN'

    def detect_from_module(self, module_name: str) -> str:
        """
        Detect branch from Python module name.

        Supports patterns:
        - aipass.prax.apps.handlers.monitoring -> PRAX
        - seed.core.validator -> SEED

        Args:
            module_name: Python module dotted name

        Returns:
            Branch name in uppercase
        """
        try:
            # Check cache
            if module_name in self.module_map:
                return self.module_map[module_name]

            # Split on dots and check first part
            parts = module_name.split('.')
            if parts:
                first_part = parts[0].upper()

                if first_part in self.known_branches:
                    self.module_map[module_name] = first_part
                    return first_part

            logger.info(f"Could not detect branch from module: {module_name}")
            return 'UNKNOWN'

        except Exception as e:
            logger.error(f"Error detecting branch from module {module_name}: {e}")
            return 'UNKNOWN'

    def reload_registry(self):
        """
        Reload BRANCH_REGISTRY.json.

        Clears caches and rebuilds lookup tables.
        Useful when registry is updated during runtime.
        """
        self.branch_map.clear()
        self.log_map.clear()
        self.module_map.clear()
        self.known_branches.clear()
        self._load_registry()
        logger.info("Registry reloaded")

    def get_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache sizes
        """
        return {
            'branch_paths': len(self.branch_map),
            'cached_lookups': len(self.log_map),
            'cached_modules': len(self.module_map),
            'known_branches': len(self.known_branches)
        }


# Singleton instance for module-level access
_detector_instance: Optional[BranchDetector] = None


def get_detector() -> BranchDetector:
    """
    Get singleton detector instance.

    Returns:
        BranchDetector instance
    """
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = BranchDetector()
    return _detector_instance


def detect_branch_from_path(file_path: str) -> str:
    """
    Public API - detect branch from path.

    Args:
        file_path: File or directory path

    Returns:
        Branch name in uppercase
    """
    return get_detector().detect_from_path(file_path)


def detect_branch_from_log(log_file: str) -> str:
    """
    Public API - detect branch from log filename.

    Args:
        log_file: Log filename or path

    Returns:
        Branch name in uppercase
    """
    return get_detector().detect_from_log(log_file)


def detect_branch_from_module(module_name: str) -> str:
    """
    Public API - detect branch from module name.

    Args:
        module_name: Python module dotted name

    Returns:
        Branch name in uppercase
    """
    return get_detector().detect_from_module(module_name)


def reload_registry():
    """Public API - reload BRANCH_REGISTRY.json"""
    get_detector().reload_registry()


def get_detector_stats() -> Dict[str, int]:
    """Public API - get cache statistics"""
    return get_detector().get_stats()


if __name__ == '__main__':
    # Quick test
    detector = BranchDetector()

    print("Branch Detector Test")
    print("=" * 50)

    test_paths = [
        "src/aipass/prax/apps/handlers/monitoring/branch_detector.py",
        "src/aipass/seedgo/core/validator.py",
        "src/aipass/flow/apps/modules/planners.py",
    ]

    print("\nPath Detection:")
    for path in test_paths:
        branch = detector.detect_from_path(path)
        print(f"  {path}")
        print(f"  -> {branch}\n")

    test_logs = [
        "seed_audit.log",
        "flow_plan.log",
        "prax_monitor_20251123.log",
    ]

    print("\nLog Detection:")
    for log in test_logs:
        branch = detector.detect_from_log(log)
        print(f"  {log} -> {branch}")

    test_modules = [
        "aipass.prax.apps.handlers.monitoring",
        "seed.core.validator",
        "flow.planners.daily",
    ]

    print("\nModule Detection:")
    for module in test_modules:
        branch = detector.detect_from_module(module)
        print(f"  {module} -> {branch}")

    print("\nCache Stats:")
    stats = detector.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
