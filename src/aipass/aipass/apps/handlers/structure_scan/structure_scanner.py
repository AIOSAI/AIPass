# =================== AIPass ====================
# Name: structure_scanner.py
# Description: Project structure validation for aipass doctor
# Version: 1.3.0
# Created: 2026-05-14
# Modified: 2026-10-27
# =============================================

"""
Structure Scanner — detect misplaced agents, init pollution, registry mismatches.

Plain data out, no Rich markup beyond the shared doctor glyphs: display belongs to the doctor module.
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.ui.progress import GLYPH_FAIL, GLYPH_PASS, GLYPH_WARN
from aipass.prax import logger
from aipass.aipass.shared.registry_discovery import registries_in


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


class PackagesUnknown(NamedTuple):
    """A root whose declared package names could not be read — unknown, not "none"."""

    root: str
    reason: str


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


def find_project_root(start: Path) -> Optional[Path]:
    """Walk up from *start* looking for a registry file or pyproject.toml with src/."""
    p = start.resolve()
    for parent in (p, *p.parents):
        if registries_in(parent):
            return parent
        if (parent / "pyproject.toml").exists() and (parent / "src").is_dir():
            return parent
        if parent == parent.parent:
            break
    return None


# dropbox and .archive are sandboxes nothing looks into: a branch copied there is not an agent.
_SCAN_SKIP_DIRS = {
    "dropbox",
    ".archive",
    ".backup",
    ".venv",
    ".git",
    "__pycache__",
    "node_modules",
    ".chroma",
    "templates",
}


def scan_agents(project_root: Path) -> List[AgentInfo]:
    """Find all agents by scanning for .trinity/passport.json under project_root."""
    agents: List[AgentInfo] = []
    for passport_path in sorted(project_root.rglob(".trinity/passport.json")):
        # Parts relative to the project: a parent of the project named dropbox is not a sandbox.
        if any(skip in passport_path.relative_to(project_root).parts for skip in _SCAN_SKIP_DIRS):
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


def _detect_package_names(project_root: Path, why: List[str]) -> Optional[set]:
    """Read pyproject.toml to find declared package directory names.

    None (reason in *why*) when the file exists but cannot be read, e.g. Python 3.10
    without tomli. Unknown is not "no packages": never measure placement against it.
    """
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return set()

    try:
        import tomllib  # stdlib 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            version = f"{sys.version_info[0]}.{sys.version_info[1]}"
            reason = f"no TOML parser: Python {version} has no tomllib and tomli is not installed"
            logger.warning("[structure_scan] %s — package names unknown for %s", reason, project_root)
            why.append(reason)
            return None

    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        logger.warning("[structure_scan] pyproject.toml parse error: %s", exc)
        why.append(f"pyproject.toml could not be parsed: {exc}")
        return None

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


def _registry_residents(registry: Path) -> "tuple[set[str], set[Path]]":
    """The names (lowercased) and directories a registry lists as its citizens."""
    data = json_handler.read_json(registry)
    if not isinstance(data, dict):
        return set(), set()
    names: set = set()
    paths: set = set()
    for entry in data.get("branches") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip().lower()
        if name:
            names.add(name)
        rel = str(entry.get("path", "")).strip()
        if rel:
            paths.add((registry.parent / rel).resolve())
    return names, paths


def resident_root(agent: AgentInfo, project_root: Path) -> Optional[Path]:
    """The project root whose registry lists this agent, walking up from the agent.

    A citizen of a project under ``projects/<name>/`` lives outside the framework's
    ``src/``; measured against it, it would warn on every scan. None: no registry claims it.
    """
    here = agent.path.resolve()
    name = agent.name.strip().lower()
    for parent in (here, *here.parents):
        for registry in registries_in(parent):
            names, paths = _registry_residents(registry)
            if (name and name in names) or here in paths:
                return parent
        if parent == project_root.resolve():
            break
    return None


def check_placement(
    agents: List[AgentInfo],
    project_root: Path,
    unknown: Optional[List[PackagesUnknown]] = None,
) -> List[PlacementIssue]:
    """Check whether each agent is in src/<package>/<agent>/ or src/<agent>/.

    Each agent is measured at the root that claims it (resident_root). A root whose
    package names are unknown goes into *unknown* once, never as a placement issue.
    """
    issues: List[PlacementIssue] = []
    packages_by_root: Dict[Path, Optional[set]] = {}
    unknown_roots: List[PackagesUnknown] = unknown if unknown is not None else []

    for agent in agents:
        home = resident_root(agent, project_root) or project_root
        src_dir = home / "src"
        if home not in packages_by_root:
            why: List[str] = []
            packages_by_root[home] = _detect_package_names(home, why)
            if packages_by_root[home] is None:  # unknown, not "no packages": shown, never measured against
                unknown_roots.append(PackagesUnknown(str(home), "; ".join(why)))
        package_names = packages_by_root[home]

        rel = None
        try:
            rel = agent.path.resolve().relative_to(src_dir.resolve())
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


def detect_pollution(agents: List[AgentInfo]) -> List[PollutionHit]:
    """Find duplicate branch names — same agent found at multiple locations.

    Keys on branch_name, never registry_id: every citizen of a healthy install shares that.
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


def check_registry_consistency(
    registry_path: Path,
    agents: List[AgentInfo],
    project_root: Optional[Path] = None,
) -> List[RegistryIssue]:
    """Validate that registry branches[].path entries match actual filesystem."""
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


def check_root_artifacts(project_root: Path, aipass_home: Path | str | None = None) -> List[RootArtifact]:
    """Detect branch-level files/dirs sitting at project root instead of inside branches.

    setup.sh puts a real .venv at the AIPASS_HOME root, so *aipass_home* exempts it there.
    """
    hits: List[RootArtifact] = []

    resolved_home = Path(aipass_home).resolve() if aipass_home else None

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
        if dirname == ".venv" and resolved_home is not None and project_root.resolve() == resolved_home:
            hits.append(
                RootArtifact(
                    name=dirname,
                    artifact_type=artifact_type,
                    severity="pass",
                    description="Standard AIPass runtime venv (AIPASS_HOME root)",
                )
            )
            continue
        hits.append(RootArtifact(name=dirname, artifact_type=artifact_type, severity=severity, description=description))

    if hits:
        logger.info("[structure_scan] found %d root artifacts at %s", len(hits), project_root)
    json_handler.log_operation("check_root_artifacts", {"count": len(hits), "root": str(project_root)})
    return hits


#: Claude Code reads AGENTS.md only when none of these sits in cwd or above.
_SHADOW_NAMES = ("CLAUDE.md", "CLAUDE.local.md")


class InstructionShadow(NamedTuple):
    """A live CLAUDE file that silences the AGENTS.md beside it in Claude Code."""

    path: Path
    agents_path: Path
    equal: bool


def find_instruction_shadows(project_root: Path) -> List[InstructionShadow]:
    """CLAUDE.md / CLAUDE.local.md at *project_root* or its .claude/, beside an AGENTS.md there."""
    dirs = (project_root, project_root / ".claude")
    agents = [d / "AGENTS.md" for d in dirs if (d / "AGENTS.md").is_file()]
    if not agents:
        return []
    shadows: List[InstructionShadow] = []
    for folder in dirs:
        beside = folder / "AGENTS.md" if (folder / "AGENTS.md").is_file() else agents[0]
        for name in _SHADOW_NAMES:
            path = folder / name
            # One file under both names (a symlink either way) says the same thing to both CLIs.
            if not path.is_file() or path.resolve() == beside.resolve():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            equal = text == beside.read_text(encoding="utf-8", errors="replace")
            shadows.append(InstructionShadow(path, beside, equal))
    json_handler.log_operation("find_instruction_shadows", {"count": len(shadows), "root": str(project_root)})
    return shadows


def disable_shadow(shadow: InstructionShadow, project_root: Path) -> "tuple[bool, str]":
    """Rename *shadow* to '<name>(disabled)' beside it. Never copies, deletes or overwrites.

    Refuses when the root holds $HOME (its .claude/CLAUDE.md is the user's own memory) or
    when the file's folder resolves outside the root, e.g. a .claude symlinked elsewhere.
    """
    root = project_root.resolve()
    home = Path.home().resolve()
    rel = shadow.path.relative_to(project_root).as_posix()
    target = shadow.path.with_name(f"{shadow.path.name}(disabled)")
    if root == home or root in home.parents:
        return False, f"Left {rel}: the project root holds $HOME, whose CLAUDE files are the user's"
    if not shadow.path.parent.resolve().is_relative_to(root):
        return False, f"Left {rel}: its folder resolves outside the project root"
    if target.exists() or target.is_symlink():
        return False, f"Left {rel}: {target.name} already exists beside it"
    shadow.path.rename(target)
    logger.info("[structure_scan] renamed instruction shadow %s -> %s", shadow.path, target.name)
    return True, f"Renamed {rel} -> {target.name}"


def disable_shadows(project_root: Path) -> "List[tuple[bool, str]]":
    """Rename every shadow under *project_root*: one (renamed, what happened) per file."""
    actions = [disable_shadow(shadow, project_root) for shadow in find_instruction_shadows(project_root)]
    if actions:
        json_handler.log_operation("disable_shadows", {"root": str(project_root), "actions": [a for _, a in actions]})
    return actions


def check_pyproject(project_root: Path) -> Dict[str, Any]:
    """Check for pyproject.toml presence at project root."""
    pyproject = project_root / "pyproject.toml"
    return {
        "found": pyproject.exists(),
        "path": str(pyproject) if pyproject.exists() else "",
    }


#: Folders spawn and the services write inside a project: tracked, they ship one installation's state.
_RUNTIME_DIR_PATTERNS = (".chroma", "docs.local", "dropbox", ".spawn", "*_json")
_RUNTIME_FILE_PATTERNS = ("*_REGISTRY.json",)


def _runtime_owner(rel: str) -> Optional[str]:
    """The runtime folder or file *rel* belongs to, project-relative, or None for a project file."""
    parts = rel.split("/")
    for depth, part in enumerate(parts[:-1]):
        if any(fnmatch.fnmatch(part, pattern) for pattern in _RUNTIME_DIR_PATTERNS):
            return "/".join(parts[: depth + 1])
    return rel if any(fnmatch.fnmatch(parts[-1], pattern) for pattern in _RUNTIME_FILE_PATTERNS) else None


def check_gitignore_coverage(project_root: Path) -> "List[tuple[str, str, str, str]]":
    """Doctor rows ``(label, glyph, detail, fix)``: runtime files on disk that git tracks, one FAIL per owner.

    Read-only: lists the index with ``ls-files``, never changes it. The AIPass source tree is not measured,
    since its .gitignore ships spawn's templates by negation on purpose."""
    label = "gitignore coverage"
    if (project_root / "src" / "aipass").is_dir() and (project_root / "pyproject.toml").is_file():
        return [(label, GLYPH_PASS, "not measured: the AIPass source tree ships its templates tracked", "")]
    try:
        listed = subprocess.run(
            ["git", "-C", str(project_root), "ls-files", "-z"], capture_output=True, encoding="utf-8", check=False
        )
    except OSError as exc:
        logger.warning("[structure_scan] ls-files could not run in %s: %s", project_root, exc)
        return [(label, GLYPH_WARN, f"not measured: git could not run ({exc})", "Install git")]
    if listed.returncode != 0:
        return [(label, GLYPH_PASS, "not a git repository: nothing tracked", "")]
    counts: Dict[str, int] = {}
    for rel in filter(None, listed.stdout.split("\0")):
        owner = _runtime_owner(rel)
        if owner and (project_root / rel).exists():
            counts[owner] = counts.get(owner, 0) + 1
    json_handler.log_operation("check_gitignore_coverage", {"root": str(project_root), "owners": len(counts)})
    rows = []
    for owner, count in sorted(counts.items()):
        recursive = " --recursive" if (project_root / owner).is_dir() else ""
        fix = f"drone @git untrack{recursive} {owner} (files stay on disk); aipass init update adds the ignore line"
        rows.append((f"{label}: {owner}", GLYPH_FAIL, f"{count} tracked file(s) one installation writes", fix))
    return rows or [(label, GLYPH_PASS, "no runtime file tracked", "")]
