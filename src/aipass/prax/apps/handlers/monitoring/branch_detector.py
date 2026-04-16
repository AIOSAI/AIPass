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

Uses AIPASS_REGISTRY.json for accurate mapping with caching for performance.
"""

from pathlib import Path
from typing import Optional, Dict, Set
import json

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler

logger = get_direct_logger()


class BranchDetector:
    """
    Detects branch ownership for files, logs, and modules.

    Uses multiple strategies:
    1. Direct path lookup from AIPASS_REGISTRY.json
    2. Parent directory traversal
    3. Filename pattern matching
    4. Caching for repeated lookups
    """

    def __init__(self):
        """Initialize detector with empty caches"""
        self.branch_map: Dict[str, str] = {}  # path -> branch
        self.log_map: Dict[str, str] = {}  # log file -> branch
        self.module_map: Dict[str, str] = {}  # module -> branch
        self.known_branches: Set[str] = set()
        self._repo_root: Optional[Path] = None
        self._external_project_cache: Dict[str, str] = {}  # dir_name -> project_name
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

    def _register_branch(self, branch: dict) -> None:
        """Register a single branch entry into the lookup tables."""
        branch_name = branch.get("name", "").upper()
        branch_path = branch.get("path", "")
        if not branch_name or not branch_path:
            return
        path = Path(branch_path).resolve()
        self.branch_map[str(path)] = branch_name
        self.known_branches.add(branch_name)
        self.branch_map[str(path) + "/"] = branch_name

    def _load_registry(self):
        """Load AIPASS_REGISTRY.json and build lookup tables."""
        try:
            registry_path = self._find_repo_root() / "AIPASS_REGISTRY.json"

            if not registry_path.exists():
                logger.warning(f"Registry not found: {registry_path}")
                self._load_fallback_branches()
                return

            with open(registry_path, encoding="utf-8") as f:
                data = json.load(f)

            branches = data.get("branches", [])
            if not branches:
                logger.warning("No branches found in registry")
                self._load_fallback_branches()
                return

            for branch in branches:
                self._register_branch(branch)

            logger.info(f"Loaded {len(self.known_branches)} branches from registry")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in registry: {e}")
            self._load_fallback_branches()
        except Exception as e:
            logger.error(f"Error loading registry: {e}")
            self._load_fallback_branches()

    def _load_fallback_branches(self):
        """Load fallback branch names when registry is unavailable"""
        fallback = ["SEEDGO", "CLI", "FLOW", "PRAX", "DRONE", "BACKUP", "SECURITY", "AIPASS"]
        self.known_branches.update(fallback)
        logger.info(f"Using fallback branches: {fallback}")

    def _resolve_external_project_name(self, project_part: str) -> str:
        """Resolve external project directory name to canonical name via _REGISTRY.json.

        Args:
            project_part: Directory name segment like 'Vera-Studio' or 'AIPL'

        Returns:
            Name from registry file stem (e.g., 'VERA-STUDIO') or uppercased dir name
        """
        for base in [Path.home() / "Projects"]:
            project_dir = base / project_part
            if not project_dir.exists():
                continue
            try:
                for item in project_dir.iterdir():
                    if item.is_file() and item.name.endswith("_REGISTRY.json"):
                        return item.stem.replace("_REGISTRY", "")
            except (OSError, PermissionError) as e:
                logger.info(f"[branch_detector] Cannot read project dir {project_dir}: {e}")
            return project_part.upper()
        return project_part.upper()

    def _parse_external_project_path(self, encoded_folder: str) -> tuple:
        """Parse encoded Claude project folder into (project_name, agent_name).

        Handles hyphens in project names by splitting on -Projects- and -src-.

        Examples:
            -home-patrick-Projects-Vera-Studio -> ('VERA-STUDIO', None)
            -home-patrick-Projects-AIPL-src-polyglot -> ('AIPL', 'POLYGLOT')
            -home-patrick-Projects-Vera-Studio-src-vera -> ('VERA-STUDIO', 'VERA')

        Returns:
            (project_name, agent_name) -- agent_name is None if no src subdir
            Returns (None, None) if cannot parse.
        """
        if not encoded_folder.startswith("-"):
            return None, None

        name = encoded_folder[1:]  # strip leading dash

        # Find -Projects- boundary
        sep = "-projects-"
        idx = name.lower().find(sep)
        if idx < 0:
            return None, None

        # Everything after -projects- is our target
        after = name[idx + len(sep) :]

        # Split on -src- to separate project from agent subdirectory
        src_sep = "-src-"
        src_idx = after.lower().find(src_sep)

        if src_idx >= 0:
            project_part = after[:src_idx]
            agent_part = after[src_idx + len(src_sep) :]
        else:
            project_part = after
            agent_part = None

        # Resolve project name via registry file on filesystem
        project_name = self._resolve_external_project_name(project_part)

        # Agent name: uppercase with hyphen preserved (polyglot -> POLYGLOT)
        agent_name = agent_part.upper() if agent_part else None

        return project_name, agent_name

    def _detect_from_claude_project(self, path_str: str) -> Optional[str]:
        """Detect PROJECT/BRANCH label from Claude Code project path encoding.

        Returns two-tier label (model suffix added by caller):
        - Internal AIPass branches: 'AIPASS/DEVPULSE'
        - External project with agent: 'AIPL/POLYGLOT'
        - External project main session: 'VERA-STUDIO'
        Sub-agents append ' SUB' to the agent/branch segment.
        """
        projects_idx = path_str.index(".claude/projects/") + len(".claude/projects/")
        remaining = path_str[projects_idx:]
        project_folder = remaining.split("/")[0]
        is_subagent = "/subagents/" in path_str
        sub_suffix = " SUB" if is_subagent else ""

        folder_lower = project_folder.lower()

        # Internal AIPass: path contains -projects-aipass-src-aipass-
        if "-projects-aipass-src-aipass-" in folder_lower:
            # Strip leading dash before decode — avoids double slash and preserves
            # normalization that treats - and _ as equivalent (handles ai_mail→ai-mail).
            name_part = project_folder[1:] if project_folder.startswith("-") else project_folder
            project_path = "/" + name_part.replace("-", "/")
            for registered_path, branch_name in self.branch_map.items():
                reg_norm = registered_path.replace("_", "/")
                proj_norm = project_path.replace("_", "/")
                if reg_norm == proj_norm or registered_path == project_path:
                    return f"AIPASS/{branch_name}{sub_suffix}"
            # Fallback: scan segments for known branch names (handles multi-word: ai_mail)
            segs = [s for s in project_folder.split("-") if s]
            for n in range(min(3, len(segs)), 0, -1):
                candidate = "_".join(segs[-n:]).upper()
                if candidate in self.known_branches:
                    return f"AIPASS/{candidate}{sub_suffix}"
            if segs:
                return f"AIPASS/{segs[-1].upper()}{sub_suffix}"
            return None

        # External project
        project_name, agent_name = self._parse_external_project_path(project_folder)
        if project_name:
            if agent_name:
                return f"{project_name}/{agent_name}{sub_suffix}"
            elif sub_suffix:
                return f"{project_name}{sub_suffix}"
            else:
                return project_name

        # Old fallback: segment scanning for known branch names
        segments = [s for s in project_folder.split("-") if s]
        if not segments:
            return None
        for i in range(len(segments) - 1, 0, -1):
            candidate = "_".join(segments[i:]).upper()
            if candidate in self.known_branches:
                return candidate
        last = segments[-1].upper()
        if last in self.known_branches:
            return last
        return None

    def _detect_from_compound_parts(self, path_parts: list) -> Optional[str]:
        """Check compound path parts for known branch names."""
        for part in path_parts:
            if "_" in part:
                for subpart in part.split("_"):
                    branch_upper = subpart.upper()
                    if branch_upper in self.known_branches:
                        return branch_upper
        return None

    def _detect_from_external_project_path(self, path: Path) -> Optional[str]:
        """Detect project/agent label from a file path under ~/Projects/.

        Covers external AIPass projects (AIPL, Vera-Studio, etc.) whose files
        are not in branch_map but live under a directory containing *_REGISTRY.json.
        AIPass itself is skipped — its branches are handled by branch_map.

        Returns labels like 'AIPL/POLYGLOT', 'VERA-STUDIO', 'AIPL/POLYGLOT TESTS'.
        """
        projects_base = Path.home() / "Projects"
        try:
            rel = path.relative_to(projects_base)
        except ValueError:
            logger.info(f"[branch_detector] Path not under ~/Projects/: {path}")
            return None

        parts = rel.parts
        if not parts:
            return None

        project_dir_name = parts[0]

        # Skip AIPass — handled by registry/branch_map (Strategy 2)
        if project_dir_name.lower() == "aipass":
            return None

        # Look up project name (cached)
        if project_dir_name in self._external_project_cache:
            project_name = self._external_project_cache[project_dir_name]
        else:
            project_dir = projects_base / project_dir_name
            project_name = None
            try:
                for item in project_dir.iterdir():
                    if item.is_file() and item.name.endswith("_REGISTRY.json"):
                        project_name = item.stem.replace("_REGISTRY", "")
                        break
            except (OSError, PermissionError) as e:
                logger.info(f"[branch_detector] Cannot scan project dir {project_dir}: {e}")
            if not project_name:
                return None  # Not an external AIPass project
            self._external_project_cache[project_dir_name] = project_name

        # Extract agent from path: {project}/src/{agent}/...
        agent_name = None
        if len(parts) > 2 and parts[1].lower() == "src":
            agent_name = parts[2].upper()

        # Append TESTS suffix when path is clearly test output
        path_str_lower = str(path).replace("\\", "/").lower()
        is_test = (
            "/tests/" in path_str_lower
            or "/test_" in path_str_lower
            or path_str_lower.endswith("_test.py")
            or path_str_lower.endswith("_test.log")
        )
        test_suffix = " TESTS" if is_test else ""

        if agent_name:
            return f"{project_name}/{agent_name}{test_suffix}"
        return f"{project_name}{test_suffix}"

    def _extract_branch_from_central(self, path_str: str, path: Path) -> Optional[str]:
        """Extract branch name from ai_mail central filename patterns."""
        if not ("AI_MAIL" in path_str or ".ai_mail" in path_str or "ai_mail" in path_str.lower()):
            return None

        name = path.name
        if ".central.json" in name:
            return name.replace(".central.json", "").upper()
        if "_central.json" in name:
            return name.replace("_central.json", "").upper()
        return None

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
            Branch name in uppercase (e.g., 'SEEDGO', 'PRAX')
        """
        try:
            path = Path(file_path).resolve()
            path_str = str(path)
            # Normalize to forward slashes for all string-based pattern matching.
            # Path.resolve() returns OS-native separators (backslashes on Windows), which
            # breaks every hardcoded '/' check. branch_map lookups still use path_str (OS-native).
            path_str_fwd = path_str.replace("\\", "/")

            # Check cache first
            if path_str in self.log_map:
                return self.log_map[path_str]

            # Strategy 0: External AIPass project files get priority over bare registry lookups.
            # AIPL branches (e.g. POLYGLOT) are registered in AIPASS_REGISTRY.json with
            # absolute paths, so Strategy 2 would return bare 'POLYGLOT' before we can
            # add the project prefix. Check external paths first to return 'AIPL/POLYGLOT TESTS'.
            _repo_root = self._find_repo_root()
            _projects_base = Path.home() / "Projects"
            _path_str_lower = path_str_fwd.lower()
            _projects_str = str(_projects_base).replace("\\", "/").lower()
            _repo_str = str(_repo_root).replace("\\", "/").lower()
            _is_external = _path_str_lower.startswith(_projects_str + "/") and not _path_str_lower.startswith(
                _repo_str + "/"
            )

            if _is_external:
                result = self._detect_from_external_project_path(path)
                if result:
                    self.log_map[path_str] = result
                    return result

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

            # Strategy 2.5: External AIPass project files (fallback for non-~/Projects/ paths)
            if not _is_external:
                result = self._detect_from_external_project_path(path)
                if result:
                    self.log_map[path_str] = result
                    return result

            # Strategy 3: Claude Code project files
            if ".claude/projects/" in path_str_fwd:
                result = self._detect_from_claude_project(path_str_fwd)
                if result:
                    self.log_map[path_str] = result
                    return result

            # Strategy 4: ai_mail central files - {BRANCH}.central.json or {BRANCH}_central.json
            result = self._extract_branch_from_central(path_str, path)
            if result:
                self.log_map[path_str] = result
                return result

            # Strategy 5: Root-level system files (repo root or .claude under it)
            repo_root = self._find_repo_root()
            if path.parent == repo_root or path.parent == repo_root / ".claude":
                self.log_map[path_str] = "SYSTEM"
                return "SYSTEM"

            # Strategy 6: Parse path for known branch names
            path_parts = path_str_fwd.lower().split("/")
            for part in path_parts:
                branch_upper = part.upper()
                if branch_upper in self.known_branches:
                    self.log_map[path_str] = branch_upper
                    return branch_upper

            # Strategy 6: Check for compound names (e.g., ai_mail -> check for AI_MAIL patterns)
            result = self._detect_from_compound_parts(path_parts)
            if result:
                self.log_map[path_str] = result
                return result

            # No match found
            logger.info(f"Could not detect branch for path: {file_path}")
            return "UNKNOWN"

        except Exception as e:
            logger.error(f"Error detecting branch from path {file_path}: {e}")
            return "UNKNOWN"

    def detect_from_log(self, log_file: str) -> str:
        """
        Detect branch from log filename.

        Supports patterns:
        - seedgo_audit.log -> SEEDGO
        - seedgo_standards_checklist.log -> SEEDGO
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
            # Handles compound names like ai_mail, backup, memory
            for branch_name in sorted(self.known_branches, key=len, reverse=True):
                prefix = branch_name.lower() + "_"
                if name.lower().startswith(prefix) or name.lower() == branch_name.lower():
                    self.log_map[name] = branch_name
                    return branch_name

            # Full path: use path detection before falling back to stem splitting.
            # This ensures ai_mail/logs/mail_*.log resolves to AI_MAIL via branch_map
            # rather than returning a truncated stem like MAIL.
            if "/" in log_file:
                return self.detect_from_path(log_file)

            # Bare filename: fallback to stem splitting
            if "_" in name:
                parts = name.split("_")
                first_part = parts[0].upper()
                self.log_map[name] = first_part
                return first_part

            # Try full name (no underscore)
            name_upper = name.upper()
            if name_upper in self.known_branches:
                self.log_map[name] = name_upper
                return name_upper

            logger.info(f"Could not detect branch from log: {log_file}")
            return "UNKNOWN"

        except Exception as e:
            logger.info(f"Error detecting branch from log {log_file}: {e}")
            return "UNKNOWN"

    def detect_from_module(self, dotted_name: str) -> str:
        """
        Detect branch from Python module name.

        Supports patterns:
        - aipass.prax.apps.handlers.monitoring -> PRAX
        - seedgo.core.validator -> SEEDGO

        Args:
            dotted_name: Python module dotted name (e.g. 'aipass.prax.apps')

        Returns:
            Branch name in uppercase
        """
        try:
            # Check cache
            if dotted_name in self.module_map:
                return self.module_map[dotted_name]

            # Split on dots and check first part
            parts = dotted_name.split(".")
            if parts:
                first_part = parts[0].upper()

                if first_part in self.known_branches:
                    self.module_map[dotted_name] = first_part
                    return first_part

            logger.info(f"Could not detect branch from module: {dotted_name}")
            return "UNKNOWN"

        except Exception as e:
            logger.error(f"Error detecting branch from module {dotted_name}: {e}")
            return "UNKNOWN"

    def reload_registry(self):
        """
        Reload AIPASS_REGISTRY.json.

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
            "branch_paths": len(self.branch_map),
            "cached_lookups": len(self.log_map),
            "cached_modules": len(self.module_map),
            "known_branches": len(self.known_branches),
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


def reload_registry():
    """Public API - reload AIPASS_REGISTRY.json"""
    get_detector().reload_registry()


if __name__ == "__main__":
    # Quick test
    detector = BranchDetector()

    print("Branch Detector Test")
    print("=" * 50)

    test_paths = [
        "src/aipass/prax/apps/handlers/monitoring/branch_detector.py",
        "src/aipass/seedgo/core/validator.py",  # seedgo branch
        "src/aipass/flow/apps/modules/planners.py",
    ]

    print("\nPath Detection:")
    for path in test_paths:
        branch = detector.detect_from_path(path)
        print(f"  {path}")
        print(f"  -> {branch}\n")

    test_logs = [
        "seedgo_audit.log",
        "flow_plan.log",
        "prax_monitor_20251123.log",
    ]

    print("\nLog Detection:")
    for log in test_logs:
        branch = detector.detect_from_log(log)
        print(f"  {log} -> {branch}")

    test_modules = [
        "aipass.prax.apps.handlers.monitoring",
        "seedgo.core.validator",
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
