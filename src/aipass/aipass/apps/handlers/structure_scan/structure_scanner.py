# =================== AIPass ====================
# Name: structure_scanner.py
# Description: Project structure validation for aipass doctor
# Version: 1.0.0
# Created: 2026-05-14
# Modified: 2026-05-14
# =============================================

"""
Structure Scanner — detect misplaced agents, init pollution, registry mismatches.

Pure scanning logic. Returns plain dicts/lists — no Rich markup.
Display concerns belong to the doctor module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

from aipass.aipass.apps.handlers.json import json_handler
from aipass.prax import logger


class AgentInfo(NamedTuple):
    """An agent discovered on disk via .trinity/passport.json."""

    name: str
    path: Path
    registry_id: str
    passport_data: Dict[str, Any]


class PlacementIssue(NamedTuple):
    """Agent placement problem."""

    agent_name: str
    actual_path: str
    expected_pattern: str
    severity: str  # "warn" or "fail"


class PollutionHit(NamedTuple):
    """Same branch name found at multiple locations."""

    agent_name: str
    locations: List[str]


class RootArtifact(NamedTuple):
    """Branch-level file or directory found at project root."""

    name: str
    artifact_type: str
    severity: str
    description: str


class RegistryIssue(NamedTuple):
    """Registry path mismatch."""

    branch_name: str
    registered_path: str
    problem: str  # "missing" or "mismatch"


# =============================================================================
# PROJECT ROOT DETECTION
# =============================================================================


def find_project_root(start: Path) -> Optional[Path]:
    """Walk up from *start* looking for a registry file or pyproject.toml with src/.

    Returns:
        Project root Path, or None if not found.
    """
    p = start.resolve()
    for parent in (p, *p.parents):
        if list(parent.glob("*_REGISTRY.json")):
            return parent
        if (parent / "pyproject.toml").exists() and (parent / "src").is_dir():
            return parent
        if parent == parent.parent:
            break
    return None


# =============================================================================
# AGENT DETECTION
# =============================================================================


_SCAN_SKIP_DIRS = {".archive", ".backup", ".venv", ".git", "__pycache__", "node_modules", ".chroma", "templates"}


def scan_agents(project_root: Path) -> List[AgentInfo]:
    """Find all agents by scanning for .trinity/passport.json under project_root.

    Returns:
        List of AgentInfo for each valid passport found.
    """
    agents: List[AgentInfo] = []
    for passport_path in sorted(project_root.rglob(".trinity/passport.json")):
        if any(skip in passport_path.parts for skip in _SCAN_SKIP_DIRS):
            continue
        agent_dir = passport_path.parent.parent
        if agent_dir == project_root:
            continue
        try:
            data = json.loads(passport_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[structure_scan] unreadable passport: %s — %s", passport_path, exc)
            continue

        branch_info = data.get("branch_info", {})
        citizenship = data.get("citizenship", {})
        name = branch_info.get("branch_name", passport_path.parent.parent.name)
        registry_id = citizenship.get("registry_id", "")
        agent_dir = passport_path.parent.parent

        agents.append(
            AgentInfo(
                name=name,
                path=agent_dir,
                registry_id=registry_id,
                passport_data=data,
            )
        )

    logger.info("[structure_scan] found %d agents under %s", len(agents), project_root)
    json_handler.log_operation("scan_agents", {"count": len(agents), "root": str(project_root)})
    return agents


# =============================================================================
# PACKAGE DETECTION
# =============================================================================


def _detect_package_names(project_root: Path) -> set:
    """Read pyproject.toml to find declared package directory names.

    Returns:
        Set of package names (e.g. {'aipass', 'aipl'}), empty if none found.
    """
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return set()

    try:
        import tomllib  # noqa: F811 — stdlib 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            logger.info("[structure_scan] no TOML parser available — skipping package detection")
            return set()

    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        logger.warning("[structure_scan] pyproject.toml parse error: %s", exc)
        return set()

    names: set = set()

    hatch_pkgs = (
        data.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {}).get("packages", [])
    )
    for pkg in hatch_pkgs:
        name = Path(pkg).name
        if name:
            names.add(name)

    setup_pkgs = data.get("tool", {}).get("setuptools", {}).get("packages", [])
    for pkg in setup_pkgs:
        if pkg:
            names.add(pkg)

    if names:
        logger.info("[structure_scan] detected packages: %s", names)
    return names


# =============================================================================
# PLACEMENT VALIDATION
# =============================================================================


def check_placement(agents: List[AgentInfo], project_root: Path) -> List[PlacementIssue]:
    """Check whether each agent is in src/<package>/<agent>/ or src/<agent>/.

    When pyproject.toml defines packages, agents at src/<name>/ where name
    is not a declared package are flagged as misplaced siblings.

    Returns:
        List of PlacementIssue for agents in unexpected locations.
    """
    src_dir = project_root / "src"
    issues: List[PlacementIssue] = []
    package_names = _detect_package_names(project_root)

    for agent in agents:
        rel = None
        try:
            rel = agent.path.relative_to(src_dir)
        except ValueError:
            logger.warning("[structure_scan] agent %s outside src/: %s", agent.name, agent.path)
            issues.append(
                PlacementIssue(
                    agent_name=agent.name,
                    actual_path=str(agent.path),
                    expected_pattern="src/<package>/<agent>/ or src/<agent>/",
                    severity="warn",
                )
            )
            continue

        parts = rel.parts
        if len(parts) == 1:
            if package_names and parts[0] not in package_names:
                issues.append(
                    PlacementIssue(
                        agent_name=agent.name,
                        actual_path=str(agent.path),
                        expected_pattern="src/<package>/<agent>/ — agent outside package framework",
                        severity="warn",
                    )
                )
            continue
        elif len(parts) == 2:
            # src/<package>/<agent>/ — valid multi-agent package layout
            continue
        else:
            issues.append(
                PlacementIssue(
                    agent_name=agent.name,
                    actual_path=str(agent.path),
                    expected_pattern="src/<package>/<agent>/ (too deeply nested)",
                    severity="warn",
                )
            )

    return issues


# =============================================================================
# POLLUTION DETECTION
# =============================================================================


def detect_pollution(agents: List[AgentInfo]) -> List[PollutionHit]:
    """Find duplicate branch names — same agent found at multiple locations.

    Keys on branch_name, not citizenship.registry_id: registry_id is
    intentionally shared by every citizen in a healthy install (the
    shared-project-credential model in spawn's fix_owner_identity), so
    grouping by it flags every healthy multi-branch project as "polluted".
    branch_name is the field that's actually meant to be unique per agent.

    Returns:
        List of PollutionHit for each branch name found at >1 path.
    """
    name_to_locations: Dict[str, List[AgentInfo]] = {}
    for agent in agents:
        if not agent.name:
            continue
        name_to_locations.setdefault(agent.name, []).append(agent)

    hits: List[PollutionHit] = []
    for name, group in name_to_locations.items():
        if len(group) > 1:
            hits.append(
                PollutionHit(
                    agent_name=name,
                    locations=[str(a.path) for a in group],
                )
            )
    return hits


# =============================================================================
# REGISTRY CONSISTENCY
# =============================================================================


def check_registry_consistency(
    registry_path: Path,
    agents: List[AgentInfo],
    project_root: Optional[Path] = None,
) -> List[RegistryIssue]:
    """Validate that registry branches[].path entries match actual filesystem.

    Returns:
        List of RegistryIssue for each problem found.
    """
    anchor = (project_root or registry_path.parent).resolve()

    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[structure_scan] registry unreadable: %s", exc)
        return [RegistryIssue("(registry)", str(registry_path), "unreadable")]

    branches = data.get("branches", [])
    agent_paths = {str(a.path.resolve()) for a in agents}
    issues: List[RegistryIssue] = []

    for branch in branches:
        name = branch.get("name", "unknown")
        path_str = branch.get("path", "")
        if not path_str:
            issues.append(RegistryIssue(name, "", "missing"))
            continue

        p = Path(path_str)
        reg_path = p.resolve() if p.is_absolute() else (anchor / p).resolve()
        if not reg_path.exists():
            issues.append(RegistryIssue(name, path_str, "missing"))
        elif str(reg_path) not in agent_paths:
            trinity = reg_path / ".trinity" / "passport.json"
            if not trinity.exists():
                issues.append(RegistryIssue(name, path_str, "no_passport"))

    return issues


# =============================================================================
# ROOT ARTIFACT DETECTION
# =============================================================================

_ROOT_ARTIFACTS = {
    ".chroma": ("chroma", "warn", "Memory vector store belongs inside branch directory"),
    ".ai_mail.local": ("mailbox", "warn", "Branch mailbox belongs inside branch directory"),
    "logs": ("logs", "warn", "Branch logs directory belongs inside branch directory"),
    ".venv": (
        "venv",
        "info",
        "Redundant venv — AIPass provides runtime via drone, use requirements.project.txt for extras",
    ),
}


def check_root_artifacts(project_root: Path) -> List[RootArtifact]:
    """Detect branch-level files/dirs sitting at project root instead of inside branches.

    Returns:
        List of RootArtifact for each misplaced item found.
    """
    hits: List[RootArtifact] = []

    for dirname, (artifact_type, severity, description) in _ROOT_ARTIFACTS.items():
        candidate = project_root / dirname
        if not candidate.exists():
            continue
        if dirname == ".venv" and candidate.is_symlink():
            hits.append(
                RootArtifact(
                    name=dirname,
                    artifact_type=artifact_type,
                    severity="pass",
                    description=f"Linked to AIPass runtime ({candidate.resolve()})",
                )
            )
            continue
        hits.append(RootArtifact(name=dirname, artifact_type=artifact_type, severity=severity, description=description))

    if hits:
        logger.info("[structure_scan] found %d root artifacts at %s", len(hits), project_root)
    json_handler.log_operation("check_root_artifacts", {"count": len(hits), "root": str(project_root)})
    return hits


# =============================================================================
# PYPROJECT CHECK
# =============================================================================


def check_pyproject(project_root: Path) -> Dict[str, Any]:
    """Check for pyproject.toml presence at project root.

    Returns:
        Dict with 'found' bool and optional 'path' string.
    """
    pyproject = project_root / "pyproject.toml"
    return {
        "found": pyproject.exists(),
        "path": str(pyproject) if pyproject.exists() else "",
    }
