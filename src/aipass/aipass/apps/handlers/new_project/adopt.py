# =================== AIPass ====================
# Name: adopt.py
# Description: aipass adopt — bring an existing projects/ directory into AIPass
# Version: 1.0.0
# Created: 2026-07-20
# Modified: 2026-07-20
# =============================================

"""
Adopt Handler — PRIVATE implementation

Business logic for `aipass adopt`. Turns an EXISTING directory at
<host>/projects/<name> into a full AIPass project: sealed registry,
resident agent, .aipass/.claude scaffold.

Unlike `aipass new` (which births a brand-new directory), adopt starts
from a directory that already has its own content — possibly its own
git repo, possibly public. Every write is existence-guarded; nothing
already present is ever overwritten. .gitignore is the one file that's
patched rather than skipped, since AIPass local state (.trinity/,
mailbox, *.local.json) must never leak into a tracked commit.

RULES:
  - Additive only — never overwrite a file that already exists
  - Never touch the target's git history (no git init/add/commit)
  - gitignore safety runs BEFORE any other AIPass file is written
  - Registry-first: mint the project registry before spawning the agent
  - dry_run performs zero filesystem writes and never calls spawn_agent
"""

from __future__ import annotations

from pathlib import Path

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.new_project import (
    _agent_home,
    _registry_name,
    _spawn_project_agent,
    _write_registry,
)
from aipass.aipass.shared import scaffold_content as sc
from aipass.aipass.shared.project_home import (
    _claude_local_settings,
    _claude_settings,
    _detect_aipass_home,
    _enroll_project,
    is_projects_child,
    is_throwaway_path,
)

GITIGNORE_MARKER = "# AIPass local state"


def _gitignore_safety(target: Path, *, dry_run: bool) -> str:
    """Ensure AIPass-managed paths are gitignored. Returns 'created', 'appended', or 'already-safe'."""
    gitignore_path = target / ".gitignore"
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")
        if GITIGNORE_MARKER in existing:
            return "already-safe"
        if not dry_run:
            separator = "" if existing.endswith("\n") else "\n"
            gitignore_path.write_text(existing + separator + "\n" + sc.gitignore(), encoding="utf-8")
        return "appended"
    if not dry_run:
        gitignore_path.write_text(sc.gitignore(), encoding="utf-8")
    return "created"


def _write_if_missing(path: Path, content: str, *, dry_run: bool, planned: list[str]) -> None:
    """Record and (unless dry_run) write *content* to *path*, but only if it doesn't already exist."""
    if path.exists():
        return
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    planned.append(str(path))


def adopt_project(target: Path, *, no_agent: bool = False, dry_run: bool = False) -> dict:
    """Adopt an existing directory at <host>/projects/<name> as a full AIPass project.

    Args:
        target: Existing directory to adopt — must be <host>/projects/<name>.
        no_agent: Skip resident-agent creation.
        dry_run: Report what WOULD happen; performs zero filesystem writes and
            never calls spawn_agent.

    Returns:
        dict with name, target, host, dry_run, registry_id, registry_file,
        files, gitignore_action, agent_created, agent_home, spawn_result.

    Raises:
        RuntimeError: target missing, not a projects/ child, already adopted,
            or a resident-agent home path collision.
    """
    target = target.resolve()
    if not target.is_dir():
        raise RuntimeError(f"'{target}' does not exist. `aipass adopt` brings in an EXISTING directory.")

    if not is_projects_child(target):
        raise RuntimeError(
            f"'{target}' is not <host>/projects/<name>. `aipass adopt` only works inside projects/ "
            "— use `aipass new` to create a fresh project instead."
        )

    existing_registry = [f for f in target.iterdir() if f.is_file() and f.name.endswith("_REGISTRY.json")]
    if existing_registry:
        raise RuntimeError(f"'{target}' is already adopted (has {existing_registry[0].name}).")

    host = target.parent.parent
    name = target.name
    reg = _registry_name(name)

    agent_home = _agent_home(target, name)
    if not no_agent and agent_home.exists() and any(agent_home.iterdir()):
        raise RuntimeError(
            f"Name collision: '{agent_home}' already exists and is non-empty — "
            "cannot seat a resident agent there. Retry with --no-agent."
        )

    aipass_home = _detect_aipass_home()
    files: list[str] = []

    # gitignore safety FIRST — nothing AIPass-managed gets written before the
    # target is confirmed to ignore it (target may be a public repo).
    gitignore_action = _gitignore_safety(target, dry_run=dry_run)

    # Registry — sealed, minted BEFORE spawn (registry-first rule)
    registry_id = None
    registry_filename = f"{reg}_REGISTRY.json"
    if not dry_run:
        registry_id, registry_filename = _write_registry(target, name)
    files.append(registry_filename)

    # .aipass/ — tier files, hooks.json, CLAUDE.md/AGENTS.md
    aipass_dir = target / ".aipass"
    if aipass_home:
        for tier_file in ("tier0_kernel.md", "tier1_navmap.md"):
            src_path = Path(aipass_home) / ".aipass" / tier_file
            if src_path.is_file():
                _write_if_missing(
                    aipass_dir / tier_file,
                    src_path.read_text(encoding="utf-8"),
                    dry_run=dry_run,
                    planned=files,
                )

        hooks_template = Path(aipass_home) / ".aipass" / "project_hooks.json"
        if hooks_template.is_file():
            hooks_dest = aipass_dir / "hooks.json"
            already_had_hooks = hooks_dest.exists()
            _write_if_missing(hooks_dest, hooks_template.read_text(encoding="utf-8"), dry_run=dry_run, planned=files)
            if not already_had_hooks and not dry_run:
                _enroll_project(target)

    for md_name in ("CLAUDE.md", "AGENTS.md"):
        dest = target / md_name
        if dest.exists():
            continue
        if aipass_home:
            tmpl = Path(aipass_home) / ".aipass" / f"project_{md_name}"
            if tmpl.is_file():
                content = tmpl.read_text(encoding="utf-8").replace("{name}", reg)
                _write_if_missing(dest, content, dry_run=dry_run, planned=files)
                continue
        if md_name == "AGENTS.md":
            _write_if_missing(dest, sc.agents_md(reg), dry_run=dry_run, planned=files)

    # .claude/settings.json — tracked, permissions only
    claude_dir = target / ".claude"
    _write_if_missing(claude_dir / "settings.json", _claude_settings(), dry_run=dry_run, planned=files)

    # .claude/settings.local.json — machine-local AIPASS_HOME + claudeMdExcludes
    # fence (gitignored). adopt only runs on <host>/projects/<name> (checked above).
    if aipass_home and not is_throwaway_path(aipass_home):
        _write_if_missing(
            claude_dir / "settings.local.json",
            _claude_local_settings(aipass_home, nested=True),
            dry_run=dry_run,
            planned=files,
        )

    # .claude/commands/prep.md
    _write_if_missing(claude_dir / "commands" / "prep.md", sc.prep_md(), dry_run=dry_run, planned=files)

    # .venv symlink → AIPass shared runtime
    if aipass_home:
        venv = Path(aipass_home) / ".venv"
        venv_link = target / ".venv"
        if venv.is_dir() and not venv_link.exists():
            if not dry_run:
                venv_link.symlink_to(venv)
            files.append(str(venv_link))

    # Resident agent — registry MUST exist first (dry_run never spawns)
    spawn_result = None
    agent_created = False
    will_have_agent = not no_agent
    if will_have_agent and not dry_run:
        spawn_result = _spawn_project_agent(target, name)
        agent_created = True
    elif will_have_agent and dry_run:
        files.append(f"{agent_home} (resident agent — planned)")

    json_handler.log_operation(
        "adopt_project",
        {"name": name, "target": str(target), "dry_run": dry_run},
        "adopt",
    )

    return {
        "name": name,
        "target": str(target),
        "host": str(host),
        "dry_run": dry_run,
        "registry_id": registry_id,
        "registry_file": registry_filename,
        "files": files,
        "gitignore_action": gitignore_action,
        "agent_created": agent_created,
        "agent_home": str(agent_home) if will_have_agent else None,
        "spawn_result": spawn_result,
    }
