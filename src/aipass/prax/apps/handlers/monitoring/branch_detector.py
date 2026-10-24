# =================== AIPass ====================
# Name: branch_detector.py
# Description: Branch Attribution Handler
# Version: 0.1.1
# Created: 2025-11-23
# Modified: 2026-10-24
# =============================================

"""
Branch Detection Handler

Reference: docs/monitor.md
"""

from pathlib import Path
from typing import Optional, Dict, Set
import json

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.repo_root import find_repo_root

logger = get_direct_logger()


def _exact_case_registries(project_dir: Path) -> list:
    """Glob for project registries, then re-check the case EXACTLY.

    ``Path.glob`` is case-insensitive on Windows and no pattern escapes it, so a
    post-filter keeps ``project_registry.json`` from passing as a trust anchor.
    """
    return sorted(path for path in project_dir.glob("*_REGISTRY.json") if path.name.endswith("_REGISTRY.json"))


class BranchDetector:
    """
    Detects branch ownership for files and logs.
    """

    def __init__(self):
        """Initialize detector with empty caches"""
        self.branch_map: Dict[str, str] = {}  # path -> branch
        self.log_map: Dict[str, str] = {}  # log file -> branch
        self.known_branches: Set[str] = set()
        self._repo_root: Optional[Path] = None
        self._external_project_cache: Dict[str, str] = {}  # dir_name -> project_name
        self._load_registry()
        json_handler.log_operation("branch_detected", {"known_branches": len(self.known_branches)})

    def _find_repo_root(self) -> Path:
        """Walk up from this file to find the repo root, never reading the cwd."""
        if self._repo_root is None:
            self._repo_root = find_repo_root(Path(__file__))
        return self._repo_root

    def _register_branch(self, branch: dict, base: "Optional[Path]" = None) -> None:
        """Register a single branch entry into the lookup tables.

        A relative path resolves against ``base`` (the registry's own directory), never the CWD.
        """
        branch_name = branch.get("name", "").upper()
        branch_path = branch.get("path", "")
        if not branch_name or not branch_path:
            return

        path = Path(branch_path)
        if not path.is_absolute():
            path = (base or self._find_repo_root()) / path
        path = path.resolve()

        # First registration wins, so a project cannot claim a name AIPass already uses.
        if branch_name in self.known_branches and str(path) not in self.branch_map:
            existing = {v for v in self.branch_map.values()}
            if branch_name in existing:
                logger.info(
                    "[branch_detector] Branch labelling: %s is already registered; ignoring the later "
                    "entry at %s. The first registration wins and nothing was changed on disk.",
                    branch_name,
                    path,
                )
                return

        self.branch_map[str(path)] = branch_name
        self.known_branches.add(branch_name)
        self.branch_map[str(path) + "/"] = branch_name

    def _load_registry(self):
        """Load AIPASS_REGISTRY.json and build lookup tables."""
        try:
            registry_path = self._find_repo_root() / "AIPASS_REGISTRY.json"

            if not registry_path.exists():
                logger.warning(
                    f"[branch_detector] Branch labelling: no branch registry at {registry_path} — "
                    f"falling back to the built-in branch list, so recently added branches may be "
                    f"labelled UNKNOWN on screen."
                )
                self._load_fallback_branches()
                return

            with open(registry_path, encoding="utf-8") as f:
                data = json.load(f)

            branches = data.get("branches", [])
            if not branches:
                logger.warning(
                    "[branch_detector] Branch labelling: the branch registry lists no branches — "
                    "falling back to the built-in branch list, so recently added branches may be "
                    "labelled UNKNOWN on screen."
                )
                self._load_fallback_branches()
                return

            for branch in branches:
                self._register_branch(branch)

            self._load_project_registries()

            logger.info(f"Loaded {len(self.known_branches)} branches from registry")

        except json.JSONDecodeError as e:
            logger.error(
                f"[branch_detector] Branch labelling: the branch registry is not valid JSON "
                f"(line {e.lineno}) — falling back to the built-in branch list, so recently added "
                f"branches may be labelled UNKNOWN on screen. The registry file was not modified."
            )
            self._load_fallback_branches()
        except Exception as e:
            logger.error(
                f"[branch_detector] Branch labelling: could not read the branch registry "
                f"({type(e).__name__}) — falling back to the built-in branch list, so recently added "
                f"branches may be labelled UNKNOWN on screen. The registry file was not modified."
            )
            self._load_fallback_branches()

    def _load_project_registries(self) -> None:
        """Register in-repo citizens declared by ``projects/*/*_REGISTRY.json``.

        Must run AFTER the main registry; one unreadable project must not cost the rest.
        """
        projects_dir = self._find_repo_root() / "projects"
        if not projects_dir.is_dir():
            return

        try:
            project_dirs = sorted(p for p in projects_dir.iterdir() if p.is_dir())
        except OSError as exc:
            logger.warning(
                "[branch_detector] Branch labelling: could not list %s (%s), so in-repo project "
                "citizens will not be resolvable by name. AIPass branches are unaffected and "
                "nothing was changed on disk.",
                projects_dir,
                type(exc).__name__,
            )
            return

        for project_dir in project_dirs:
            for registry_file in _exact_case_registries(project_dir):
                try:
                    data = json.loads(registry_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "[branch_detector] Branch labelling: %s is unreadable (%s), so its citizens "
                        "cannot be scoped or labelled by name. Every other project was still loaded "
                        "and the file was not modified.",
                        registry_file,
                        type(exc).__name__,
                    )
                    continue
                if not isinstance(data, dict):
                    continue
                for branch in data.get("branches", []) or []:
                    if isinstance(branch, dict):
                        self._register_branch(branch, base=project_dir)

    def _load_fallback_branches(self):
        """Load fallback branch names when registry is unavailable"""
        fallback = ["SEEDGO", "CLI", "FLOW", "PRAX", "DRONE", "BACKUP", "SECURITY", "AIPASS"]
        self.known_branches.update(fallback)
        logger.info(f"Using fallback branches: {fallback}")

    def _resolve_external_project_name(self, project_part: str) -> str:
        """Resolve external project directory name to canonical name via _REGISTRY.json."""
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

        Splits on -Projects- and -src-, as project names hold hyphens (-home-user-Projects-Vera-Studio).
        """
        if not encoded_folder.startswith("-"):
            return None, None

        name = encoded_folder[1:]  # strip leading dash

        sep = "-projects-"
        idx = name.lower().find(sep)
        if idx < 0:
            return None, None

        after = name[idx + len(sep) :]

        src_sep = "-src-"
        src_idx = after.lower().find(src_sep)

        if src_idx >= 0:
            project_part = after[:src_idx]
            agent_part = after[src_idx + len(src_sep) :]
        else:
            project_part = after
            agent_part = None

        project_name = self._resolve_external_project_name(project_part)

        agent_name = agent_part.upper() if agent_part else None

        return project_name, agent_name

    def _detect_from_claude_project(self, path_str: str) -> Optional[str]:
        """Detect PROJECT/BRANCH label from Claude Code project path encoding."""
        projects_idx = path_str.index(".claude/projects/") + len(".claude/projects/")
        remaining = path_str[projects_idx:]
        project_folder = remaining.split("/")[0]
        is_subagent = "/subagents/" in path_str
        sub_suffix = " SUB" if is_subagent else ""

        folder_lower = project_folder.lower()

        if "-projects-aipass-src-aipass-" in folder_lower:
            # The encoding turns _ into -, so compare with - and _ as equivalent (ai_mail).
            name_part = project_folder[1:] if project_folder.startswith("-") else project_folder
            project_path = "/" + name_part.replace("-", "/")
            for registered_path, branch_name in self.branch_map.items():
                reg_norm = registered_path.replace("_", "/")
                proj_norm = project_path.replace("_", "/")
                if reg_norm == proj_norm or registered_path == project_path:
                    return f"AIPASS/{branch_name}{sub_suffix}"
            segs = [s for s in project_folder.split("-") if s]
            for n in range(min(3, len(segs)), 0, -1):
                candidate = "_".join(segs[-n:]).upper()
                if candidate in self.known_branches:
                    return f"AIPASS/{candidate}{sub_suffix}"
            if segs:
                return f"AIPASS/{segs[-1].upper()}{sub_suffix}"
            return None

        project_name, agent_name = self._parse_external_project_path(project_folder)
        if project_name:
            if agent_name:
                return f"{project_name}/{agent_name}{sub_suffix}"
            elif sub_suffix:
                return f"{project_name}{sub_suffix}"
            else:
                return project_name

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

    def _detect_from_passport(self, path: Path) -> Optional[str]:
        """Walk up to the nearest ``.trinity/passport.json`` and read its name.

        Stops at the repo root so a stray passport outside the tree cannot capture files.
        """
        repo_root = self._find_repo_root()
        for parent in path.parents:
            passport = parent / ".trinity" / "passport.json"
            if passport.is_file():
                try:
                    data = json.loads(passport.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as exc:
                    logger.info(
                        "[branch_detector] Passport at %s is unreadable (%s); falling back to path "
                        "matching for this file.",
                        passport,
                        type(exc).__name__,
                    )
                    return None
                name = (data.get("branch_info", {}) or {}).get("branch_name", "")
                return str(name).upper() or None
            if parent == repo_root:
                break
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
        """Detect project/agent label from a file path under ~/Projects/."""
        projects_base = Path.home() / "Projects"
        try:
            rel = path.relative_to(projects_base)
        except ValueError:
            logger.info(f"[branch_detector] Ignoring a file outside the watched area (~/Projects/): {path}")
            return None

        parts = rel.parts
        if not parts:
            return None

        project_dir_name = parts[0]

        if project_dir_name.lower() == "aipass":
            return None

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

        agent_name = None
        if len(parts) > 2 and parts[1].lower() == "src":
            agent_name = parts[2].upper()

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
        """
        try:
            path = Path(file_path).resolve()
            path_str = str(path)
            # String matching needs '/' (Windows resolves to backslashes); branch_map keys stay native.
            path_str_fwd = path_str.replace("\\", "/")

            if path_str in self.log_map:
                return self.log_map[path_str]

            # External projects first: AIPL branches sit in AIPASS_REGISTRY.json too, and
            # the parent walk would return bare 'POLYGLOT' without the 'AIPL/' prefix.
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

            if path_str in self.branch_map:
                result = self.branch_map[path_str]
                self.log_map[path_str] = result
                return result

            for parent in path.parents:
                parent_str = str(parent)
                if parent_str in self.branch_map:
                    result = self.branch_map[parent_str]
                    self.log_map[path_str] = result
                    return result

            if not _is_external:
                result = self._detect_from_external_project_path(path)
                if result:
                    self.log_map[path_str] = result
                    return result

            if ".claude/projects/" in path_str_fwd:
                result = self._detect_from_claude_project(path_str_fwd)
                if result:
                    self.log_map[path_str] = result
                    return result

            result = self._extract_branch_from_central(path_str, path)
            if result:
                self.log_map[path_str] = result
                return result

            repo_root = self._find_repo_root()
            if path.parent == repo_root or path.parent == repo_root / ".claude":
                self.log_map[path_str] = "SYSTEM"
                return "SYSTEM"

            # The passport outranks everything below, which guesses from path text
            # (the repo directory AIPass would label every file AIPASS).
            result = self._detect_from_passport(path)
            if result:
                self.log_map[path_str] = result
                return result

            path_parts = path_str_fwd.lower().split("/")
            for part in path_parts:
                branch_upper = part.upper()
                if branch_upper in self.known_branches:
                    self.log_map[path_str] = branch_upper
                    return branch_upper

            result = self._detect_from_compound_parts(path_parts)
            if result:
                self.log_map[path_str] = result
                return result

            logger.info(f"Could not detect branch for path: {file_path}")
            return "UNKNOWN"

        except Exception as e:
            logger.error(
                f"[branch_detector] Branch labelling failed for a file path — unexpected "
                f"{type(e).__name__} on {file_path}; the live monitor will show this one as UNKNOWN. "
                f"The file itself is fine and the event is still displayed."
            )
            return "UNKNOWN"

    def detect_from_log(self, log_file: str) -> str:
        """
        Detect branch from log filename.
        """
        try:
            name = Path(log_file).stem

            if name in self.log_map:
                return self.log_map[name]

            # Longest match wins, so compound names like ai_mail resolve whole.
            for branch_name in sorted(self.known_branches, key=len, reverse=True):
                prefix = branch_name.lower() + "_"
                if name.lower().startswith(prefix) or name.lower() == branch_name.lower():
                    self.log_map[name] = branch_name
                    return branch_name

            # A full path goes to path detection first: ai_mail/logs/mail_*.log is AI_MAIL, not MAIL.
            if "/" in log_file:
                return self.detect_from_path(log_file)

            if "_" in name:
                parts = name.split("_")
                first_part = parts[0].upper()
                self.log_map[name] = first_part
                return first_part

            name_upper = name.upper()
            if name_upper in self.known_branches:
                self.log_map[name] = name_upper
                return name_upper

            logger.info(f"Could not detect branch from log: {log_file}")
            return "UNKNOWN"

        except Exception as e:
            logger.info(f"Error detecting branch from log {log_file}: {e}")
            return "UNKNOWN"


_detector_instance: Optional[BranchDetector] = None


def get_detector() -> BranchDetector:
    """
    Get singleton detector instance.
    """
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = BranchDetector()
    return _detector_instance


def detect_branch_from_path(file_path: str) -> str:
    """
    Public API - detect branch from path.
    """
    return get_detector().detect_from_path(file_path)


def detect_branch_from_log(log_file: str) -> str:
    """
    Public API - detect branch from log filename.
    """
    return get_detector().detect_from_log(log_file)


if __name__ == "__main__":
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
