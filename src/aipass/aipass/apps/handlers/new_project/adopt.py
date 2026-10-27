# =================== AIPass ====================
# Name: adopt.py
# Description: aipass adopt — bring an existing projects/ directory into AIPass
# Version: 1.3.0
# Created: 2026-07-20
# Modified: 2026-10-26
# =============================================

"""
Adopt Handler — PRIVATE implementation

Additive only, and never the target's git history. .gitignore alone is patched rather
than skipped: AIPass local state must never leak into a tracked commit.
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
from aipass.aipass.apps.handlers.init import scaffold_manifest as sm
from aipass.aipass.apps.handlers.init.bootstrap import (
    LINK_STATE_MISSING,
    PREP_SKILL_REL,
    SKILLS_LINK_REL,
    SWITCH_PAIR,
    _link_venv,
    _managed_manifest_entries,
    link_skills,
    shared_skills_state,
)
from aipass.aipass.shared import scaffold_content as sc
from aipass.aipass.shared.project_home import (
    claude_local_settings,
    _claude_settings,
    _detect_aipass_home,
    _enroll_project,
    agents_md_seed,
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
            sm.write_text_lf(gitignore_path, existing + separator + "\n" + sc.gitignore())
        return "appended"
    if not dry_run:
        sm.write_text_lf(gitignore_path, sc.gitignore())
    return "created"


def _write_if_missing(path: Path, content: str, *, dry_run: bool, planned: list[str]) -> None:
    """Record and (unless dry_run) write *content* to *path*, but only if it doesn't already exist."""
    if path.exists():
        return
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        sm.write_text_lf(path, content)
    planned.append(str(path))


def adopt_project(target: Path, *, no_agent: bool = False, dry_run: bool = False) -> dict:
    """Adopt an existing directory at <host>/projects/<name> as a full AIPass project.

    ``dry_run`` performs zero filesystem writes and never calls spawn_agent.
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
    notes: list[str] = []

    # First: the target may be a public repo, so nothing AIPass-managed lands before it is ignored.
    gitignore_action = _gitignore_safety(target, dry_run=dry_run)

    # Minted before spawn: registry-first.
    registry_id = None
    registry_filename = f"{reg}_REGISTRY.json"
    if not dry_run:
        registry_id, registry_filename = _write_registry(target, name)
    files.append(registry_filename)

    # A half-adopted tree keeps no registry, so a rerun is not refused as already adopted.
    try:
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
                _write_if_missing(
                    hooks_dest, hooks_template.read_text(encoding="utf-8"), dry_run=dry_run, planned=files
                )
                if not already_had_hooks and not dry_run:
                    _enroll_project(target)

        for md_name in sm.SEED_FILES:
            _write_if_missing(target / md_name, agents_md_seed(reg, aipass_home), dry_run=dry_run, planned=files)

        claude_dir = target / ".claude"
        _write_if_missing(claude_dir / "settings.json", _claude_settings(), dry_run=dry_run, planned=files)

        # nested=True holds: adopt only runs on <host>/projects/<name>, checked above.
        if aipass_home and not is_throwaway_path(aipass_home):
            _write_if_missing(
                claude_dir / "settings.local.json",
                claude_local_settings(aipass_home, nested=True),
                dry_run=dry_run,
                planned=files,
            )

        _write_if_missing(target / PREP_SKILL_REL, sc.prep_skill_md(), dry_run=dry_run, planned=files)
        for rel, content in SWITCH_PAIR:
            _write_if_missing(target / rel, content(), dry_run=dry_run, planned=files)
        if shared_skills_state(target)["link"] == LINK_STATE_MISSING:
            note = None if dry_run else link_skills(target)
            notes.extend([note] if note else [])
            files.append(str(target / SKILLS_LINK_REL))

        if aipass_home:
            venv = Path(aipass_home) / ".venv"
            venv_link = target / ".venv"
            if venv.is_dir() and not venv_link.exists():
                if not dry_run:
                    _link_venv(venv_link, venv)
                files.append(str(venv_link))

        # The manifest lets `init update` tell a template change from a project edit; adopt
        # stamps only what it wrote, since the tree's pre-existing files are the project's.
        if not dry_run:
            written = {rel: h for rel, h in _managed_manifest_entries(target).items() if str(target / rel) in files}
            manifest_file = sm.write_manifest(target, written)
            files.append(str(manifest_file))
        else:
            files.append(str(sm.manifest_path(target)))

        spawn_result = None
        agent_created = False
        will_have_agent = not no_agent
        if will_have_agent and not dry_run:
            spawn_result = _spawn_project_agent(target, name)
            agent_created = True
        elif will_have_agent and dry_run:
            files.append(f"{agent_home} (resident agent — planned)")
    except BaseException:
        if not dry_run:
            (target / registry_filename).unlink(missing_ok=True)
        raise

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
        "notes": notes,
    }
