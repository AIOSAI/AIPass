# =================== AIPass ====================
# Name: __init__.py
# Description: New project handler — create projects inside AIPass
# Version: 1.0.0
# Created: 2026-07-17
# Modified: 2026-07-17
# =============================================

"""
New Project Handler — creates projects inside AIPass installations.

Business logic for `aipass new`. Creates a project at <host>/projects/<name>
with its own git repo, registry, and optional AIPass agent.

Flow: find host -> validate -> mkdir -> mint registry (FIRST) ->
      write template -> scaffold AIPass files -> git init -> optional agent.

RULES:
  - Registry MUST be minted before any spawn call
  - git init via subprocess (hooks git gate only intercepts agent Bash)
  - Cleanup on failure: partial project is worse than no project
"""

import json
import re
import shutil
import subprocess
import uuid
from datetime import date
from pathlib import Path

from aipass.aipass.shared import scaffold_content as sc
from aipass.prax import logger
from aipass.spawn import spawn_agent

TEMPLATES = ("empty", "python")


def find_host_root(start: Path) -> Path | None:
    """Walk up from *start* to find the AIPass host installation root.

    Returns the directory containing ``*_REGISTRY.json``, or ``None``.
    """
    for p in [start, *start.parents]:
        try:
            entries = list(p.iterdir())
        except OSError:
            continue
        for f in entries:
            try:
                if f.is_file() and f.name.endswith("_REGISTRY.json"):
                    return p
            except OSError:
                continue
    return None


def _validate_name(name: str) -> str:
    if not name:
        raise ValueError("Project name cannot be empty")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", name):
        raise ValueError(
            f"Invalid project name '{name}'. "
            "Must start with a letter, contain only letters, digits, hyphens, underscores."
        )
    return name


def _registry_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9_-]", "_", name.upper()).strip("_")


def _git(args: list[str], cwd: Path) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


# ── registry ────────────────────────────────────────────────────────────


def _write_registry(target: Path, name: str) -> tuple[str, str]:
    """Mint the project registry. Returns ``(registry_id, filename)``."""
    registry_id = str(uuid.uuid4())
    today = date.today().isoformat()
    reg = _registry_name(name)
    filename = f"{reg}_REGISTRY.json"

    data = {
        "metadata": {
            "id": registry_id,
            "name": reg,
            "version": "1.0.0",
            "created": today,
            "last_updated": today,
            "total_branches": 0,
        },
        "branches": [],
    }
    (target / filename).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return registry_id, filename


# ── templates ───────────────────────────────────────────────────────────


def _write_template(target: Path, name: str, template: str) -> list[str]:
    """Write template-specific files. Returns relative paths created."""
    created: list[str] = []

    (target / "README.md").write_text(
        f"# {name}\n\nCreated with `aipass new`. Template: {template}.\n",
        encoding="utf-8",
    )
    created.append("README.md")

    (target / ".gitignore").write_text(sc.gitignore(), encoding="utf-8")
    created.append(".gitignore")

    if template == "python":
        pkg = name.replace("-", "_").lower()
        (target / "pyproject.toml").write_text(
            "[build-system]\n"
            'requires = ["setuptools>=61.0"]\n'
            'build-backend = "setuptools.build_meta"\n\n'
            "[project]\n"
            f'name = "{name}"\n'
            'version = "0.1.0"\n'
            f'description = "{name} — born deployable"\n'
            'requires-python = ">=3.10"\n\n'
            "[tool.setuptools.packages.find]\n"
            'where = ["src"]\n\n'
            "[tool.pytest.ini_options]\n"
            'testpaths = ["src"]\n'
            'pythonpath = ["src"]\n',
            encoding="utf-8",
        )
        created.append("pyproject.toml")
        src = target / "src" / pkg
        src.mkdir(parents=True)
        (src / "__init__.py").write_text(
            f'"""{name} — born deployable."""\n\n__version__ = "0.1.0"\n',
            encoding="utf-8",
        )
        created.append(f"src/{pkg}/__init__.py")

    return created


# ── AIPass scaffold ─────────────────────────────────────────────────────


def _scaffold_aipass(target: Path, name: str) -> list[str]:
    """Write AIPass scaffold files (tiers, hooks, CLAUDE.md, settings, .venv)."""
    from aipass.aipass.shared.project_home import (
        _claude_local_settings,
        _claude_settings,
        _detect_aipass_home,
        _enroll_project,
        is_projects_child,
        is_throwaway_path,
    )

    created: list[str] = []
    aipass_home = _detect_aipass_home()
    reg = _registry_name(name)

    # .aipass/
    aipass_dir = target / ".aipass"
    aipass_dir.mkdir(exist_ok=True)

    # Tier files
    if aipass_home:
        for tier_file in ("tier0_kernel.md", "tier1_navmap.md"):
            dest = aipass_dir / tier_file
            src_path = Path(aipass_home) / ".aipass" / tier_file
            if src_path.is_file():
                shutil.copy2(str(src_path), str(dest))
                created.append(f".aipass/{tier_file}")

    # hooks.json + trust enrollment
    if aipass_home:
        template = Path(aipass_home) / ".aipass" / "project_hooks.json"
        if template.is_file():
            shutil.copy2(str(template), str(aipass_dir / "hooks.json"))
            created.append(".aipass/hooks.json")
            _enroll_project(target)

    # CLAUDE.md, AGENTS.md
    for md_name in ("CLAUDE.md", "AGENTS.md"):
        dest = target / md_name
        if dest.exists():
            continue
        if aipass_home:
            tmpl = Path(aipass_home) / ".aipass" / f"project_{md_name}"
            if tmpl.is_file():
                content = tmpl.read_text(encoding="utf-8").replace("{name}", reg)
                dest.write_text(content, encoding="utf-8")
                created.append(md_name)
                continue
        if md_name == "AGENTS.md":
            dest.write_text(sc.agents_md(reg), encoding="utf-8")
            created.append(md_name)

    # .claude/settings.json — tracked, permissions only (no machine-local paths)
    claude_dir = target / ".claude"
    claude_dir.mkdir(exist_ok=True)
    (claude_dir / "settings.json").write_text(
        _claude_settings(),
        encoding="utf-8",
    )
    created.append(".claude/settings.json")

    # .claude/settings.local.json — machine-local AIPASS_HOME + claudeMdExcludes
    # fence (gitignored). `aipass new` always creates under <host>/projects/<name>.
    if aipass_home and not is_throwaway_path(aipass_home):
        (claude_dir / "settings.local.json").write_text(
            _claude_local_settings(aipass_home, nested=is_projects_child(target)),
            encoding="utf-8",
        )
        created.append(".claude/settings.local.json")

    # .claude/commands/prep.md
    commands_dir = claude_dir / "commands"
    commands_dir.mkdir(exist_ok=True)
    (commands_dir / "prep.md").write_text(sc.prep_md(), encoding="utf-8")
    created.append(".claude/commands/prep.md")

    # .venv symlink
    if aipass_home:
        venv = Path(aipass_home) / ".venv"
        if venv.is_dir():
            link = target / ".venv"
            link.symlink_to(venv)
            created.append(".venv")

    return created


# ── git ─────────────────────────────────────────────────────────────────


def _git_init(target: Path, name: str, template: str) -> None:
    """Initialize git repo with birth commit. Guards against re-init."""
    if (target / ".git").exists():
        raise RuntimeError(f"'{target}' already has a .git directory")
    _git(["init", "-b", "main"], target)
    _git(["add", "-A"], target)
    _git(
        ["commit", "-m", f"birth: {name} ({template} template) via aipass new"],
        target,
    )


# ── agent (via @spawn) ──────────────────────────────────────────────────


def _agent_home(project_root: Path, name: str) -> Path:
    """Compute the agent home directory: src/<pkg>/<pkg>/."""
    pkg = name.replace("-", "_").lower()
    return project_root / "src" / pkg / pkg


def _spawn_project_agent(project_root: Path, name: str) -> dict:
    """Create the project agent via spawn_agent().

    Agent lives at src/<pkg>/<pkg>/ inside the project. Spawn discovers
    the project-local registry (minted earlier by _write_registry) by
    walking up from the agent home to the project root.
    """
    home = _agent_home(project_root, name)
    result = spawn_agent(
        target_path=str(home),
        role="project_agent",
        purpose=f"Resident agent of the {name} project.",
        citizen_class="project_agent",
    )
    if not result.get("success"):
        raise RuntimeError(f"spawn_agent failed: {result.get('error', 'unknown')}")
    logger.info(
        "[aipass new] agent spawned via @spawn: %s (%d files)",
        result["branch_name"],
        result["files_copied"],
    )
    return result


# ── public API ──────────────────────────────────────────────────────────


def create_project(
    name: str,
    template: str = "empty",
    no_agent: bool = False,
) -> dict:
    """Create a new project inside the AIPass host installation.

    Returns:
        dict with name, template, target, host, registry_id, registry_file,
        files, agent_spawned.

    Raises:
        ValueError: Invalid name or template.
        RuntimeError: Not inside AIPass, target exists, git failure.
    """
    _validate_name(name)
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template '{template}'. Choose from: {', '.join(TEMPLATES)}")

    host = find_host_root(Path.cwd())
    if host is None:
        raise RuntimeError(
            "Not inside an AIPass installation (no *_REGISTRY.json found). "
            "`aipass new` creates projects inside the AIPass environment."
        )

    target = host / "projects" / name
    if target.exists():
        raise RuntimeError(f"Project already exists: {target}")

    target.mkdir(parents=True)

    try:
        registry_id, registry_file = _write_registry(target, name)
        logger.info("[aipass new] registry minted: %s (%s)", registry_file, registry_id)

        template_files = _write_template(target, name, template)
        scaffold_files = _scaffold_aipass(target, name)

        spawn_result = None
        if not no_agent:
            spawn_result = _spawn_project_agent(target, name)

        _git_init(target, name, template)
        logger.info("[aipass new] git repo initialized with birth commit")

        return {
            "name": name,
            "template": template,
            "target": str(target),
            "host": str(host),
            "registry_id": registry_id,
            "registry_file": registry_file,
            "files": template_files + scaffold_files,
            "agent_created": spawn_result is not None,
            "agent_home": str(_agent_home(target, name)) if spawn_result else None,
            "spawn_result": spawn_result,
        }
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        raise
