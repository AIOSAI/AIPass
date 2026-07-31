# =================== AIPass ====================
# Name: bootstrap.py
# Description: Init handler — bootstrap an AIPass project in any directory
# Version: 2.0.0
# Created: 2026-03-14
# Modified: 2026-04-22
# =============================================

"""
Init Bootstrap Handler - PRIVATE implementation

Business logic for `aipass init`. Creates the project scaffold:
   1. {NAME}_REGISTRY.json            — project registry with UUID
   2. .aipass/tier0_kernel.md         — tier 0 kernel prompt (every turn)
   2b..aipass/tier1_navmap.md         — tier 1 navigation map (periodic)
   3. CLAUDE.md                       — project prompt (Claude Code reads this)
   4. AGENTS.md                       — Codex equivalent of CLAUDE.md
   5. README.md                       — getting started guide
   6. .gitignore                      — standard AIPass ignores
   7. .claude/settings.json           — Claude Code hooks configuration
   8. src/                            — directory where agents live
   9. .ai_mail.local/inbox.json       — empty project mailbox

Projects are NOT citizens — no .trinity/ directory. Identity lives in the
registry JSON. Init is re-runnable: existing files are skipped, not errors.

RULES:
  - Pure Python only (no module/prax/cli imports)
  - Returns dict, raises exceptions on errors
  - No hardcoded paths
"""

import json
import logging
import re
import shutil
import uuid
from datetime import date
from pathlib import Path

from aipass.aipass.shared import scaffold_content as sc
from aipass.aipass.shared.project_home import (
    _claude_local_settings,
    _claude_settings,
    _detect_aipass_home,
    _enroll_project,
    _merge_local_settings,
    is_projects_child,
    is_throwaway_path,
)

logger = logging.getLogger(__name__)

_STALE_MANAGED_FILES: list[Path] = [
    Path(".aipass") / "aipass_global_prompt.md",
]


def _sanitize_name(raw: str) -> str:
    """Sanitize a project name for use in filenames.

    Replaces non-alphanumeric characters (except underscore/hyphen) with
    underscores and strips leading/trailing underscores.
    """
    return re.sub(r"[^A-Z0-9_-]", "_", raw.upper()).strip("_")


def _hook_fingerprint(hook_entry: dict) -> str:
    """Extract a comparable fingerprint from a hook entry."""
    commands = []
    for h in hook_entry.get("hooks", []):
        cmd = h.get("command", "")
        commands.append(cmd.strip())
    return "|".join(sorted(commands))


def _merge_settings(existing: dict, generated: dict) -> dict:
    """Merge AIPass-generated settings with existing user settings.

    Hooks are no longer distributed to projects (provider handles them).
    On update, strip any previously-injected AIPass hooks from project
    settings while preserving genuine user hooks.
    """
    merged = {}

    _aipass_hook_markers = (
        ".claude/hooks/",
        "aipass_global_prompt.md",
        "aipass_local_prompt.md",
    )

    existing_hooks = existing.get("hooks", {})
    if existing_hooks:
        cleaned_hooks: dict[str, list] = {}
        for event, entries in existing_hooks.items():
            user_entries = []
            for entry in entries:
                fp = _hook_fingerprint(entry)
                if not any(marker in fp for marker in _aipass_hook_markers):
                    user_entries.append(entry)
            if user_entries:
                cleaned_hooks[event] = user_entries
        if cleaned_hooks:
            merged["hooks"] = cleaned_hooks

    # env: AIPASS_HOME is machine-local — never tracked (see settings.local.json).
    # Strip it from any previously-tracked settings.json; preserve other user vars.
    existing_env = {k: v for k, v in existing.get("env", {}).items() if k != "AIPASS_HOME"}
    if existing_env:
        merged["env"] = existing_env

    # Merge permissions: union deny/ask lists
    existing_perms = existing.get("permissions", {})
    generated_perms = generated.get("permissions", {})
    merged_perms: dict[str, list] = {}
    for key in ("deny", "ask", "allow"):
        existing_rules = existing_perms.get(key, [])
        generated_rules = generated_perms.get(key, [])
        seen: set[str] = set()
        combined: list[str] = []
        for rule in generated_rules + existing_rules:
            if rule not in seen:
                seen.add(rule)
                combined.append(rule)
        if combined:
            merged_perms[key] = combined
    if merged_perms:
        merged["permissions"] = merged_perms

    # Preserve any other top-level keys from existing settings
    for key in existing:
        if key not in merged:
            merged[key] = existing[key]

    return merged


def _merge_hooks_json(existing: dict, template: dict) -> dict:
    """Union-merge hooks.json: preserve user enabled values, add new hooks/events."""
    merged: dict = {}
    meta_keys = {"_comment", "hooks_enabled"}

    if "_comment" in template:
        merged["_comment"] = template["_comment"]
    elif "_comment" in existing:
        merged["_comment"] = existing["_comment"]

    if "hooks_enabled" in existing:
        merged["hooks_enabled"] = existing["hooks_enabled"]
    elif "hooks_enabled" in template:
        merged["hooks_enabled"] = template["hooks_enabled"]

    all_events: set[str] = set()
    for key in existing:
        if key not in meta_keys:
            all_events.add(key)
    for key in template:
        if key not in meta_keys:
            all_events.add(key)

    for event in sorted(all_events):
        existing_hooks = existing.get(event, {})
        template_hooks = template.get(event, {})
        merged_hooks: dict = {}

        for hook_name, hook_data in existing_hooks.items():
            merged_hooks[hook_name] = dict(hook_data)

        for hook_name, hook_data in template_hooks.items():
            if hook_name in merged_hooks:
                user_enabled = merged_hooks[hook_name].get("enabled")
                merged_hooks[hook_name] = dict(hook_data)
                if user_enabled is not None:
                    merged_hooks[hook_name]["enabled"] = user_enabled
            else:
                merged_hooks[hook_name] = dict(hook_data)

        if merged_hooks:
            merged[event] = merged_hooks

    return merged


def _guard_init(target: Path, *, allow_projects_child: bool = False) -> None:
    """Block init if target is inside an agent branch or existing project.

    When *allow_projects_child* is True, the nested-project checks are
    skipped for targets that are ``<host>/projects/<name>``.  This is used
    by ``aipass new`` to create projects inside the installation.

    Raises RuntimeError with explanation if init should not proceed.
    """
    target = target.resolve()
    # Block: target IS an agent branch (has passport)
    if (target / ".trinity" / "passport.json").is_file():
        raise RuntimeError(
            f"BLOCKED: '{target}' is an agent branch (has .trinity/passport.json). "
            "Agents are managed by 'drone @spawn', not 'aipass init'."
        )
    # Block: target is INSIDE an agent branch (passport above us)
    for parent in target.parents:
        if (parent / ".trinity" / "passport.json").is_file():
            raise RuntimeError(
                f"BLOCKED: '{target}' is inside agent branch '{parent.name}'. "
                "Cannot run aipass init inside an agent directory."
            )
        if parent == parent.parent:
            break
    # Block: target already has a registry (is already a project)
    for f in target.iterdir() if target.is_dir() else []:
        if f.is_file() and f.name.endswith("_REGISTRY.json"):
            if allow_projects_child and is_projects_child(target):
                break
            raise RuntimeError(
                f"BLOCKED: '{target}' is already an AIPass project (has {f.name}). "
                "Use 'aipass init update' to upgrade an existing project."
            )
    # Block: target is inside an existing project
    for parent in target.parents:
        if not parent.is_dir():
            continue
        for f in parent.iterdir():
            if f.is_file() and f.name.endswith("_REGISTRY.json"):
                if allow_projects_child and is_projects_child(target):
                    return
                raise RuntimeError(
                    f"BLOCKED: '{target}' is inside AIPass project at '{parent}' (has {f.name}). "
                    "Cannot create a nested project."
                )
        if parent == parent.parent:
            break


def init_project(
    target: Path,
    project_name: str | None = None,
    *,
    allow_projects_child: bool = False,
) -> dict:
    """Initialize an AIPass project in the target directory.

    Args:
        target: Directory to initialize
        project_name: Name for the registry (defaults to directory name)
        allow_projects_child: When True, allow init inside ``<host>/projects/<name>``.

    Returns:
        dict with registry_id, registry_file, project_name, target, created_files

    Raises:
        ValueError: If project name is empty after sanitization
        RuntimeError: If target is inside an agent branch or existing project
    """
    target = target.resolve()
    _guard_init(target, allow_projects_child=allow_projects_child)
    if not target.exists():
        target.mkdir(parents=True)

    raw_name = project_name or target.name
    name = _sanitize_name(raw_name)
    if not name:
        raise ValueError(f"Cannot derive project name from '{raw_name}'. Pass a project name explicitly.")

    registry_id = str(uuid.uuid4())
    today = date.today().isoformat()
    created = []
    aipass_home = _detect_aipass_home()

    # 1. Registry (skip if exists — init is re-runnable)
    registry_filename = f"{name}_REGISTRY.json"
    registry_path = target / registry_filename
    if registry_path.exists():
        # Read existing registry to get its ID
        existing = json.loads(registry_path.read_text(encoding="utf-8"))
        registry_id = existing["metadata"]["id"]
    else:
        registry_data = {
            "metadata": {
                "id": registry_id,
                "name": name,
                "version": "1.0.0",
                "created": today,
                "last_updated": today,
                "total_branches": 0,
            },
            "branches": [],
        }
        registry_path.write_text(
            json.dumps(registry_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        created.append(str(registry_path))

    # 2. .aipass/
    aipass_dir = target / ".aipass"
    aipass_dir.mkdir(exist_ok=True)

    # 2. .aipass/tier0_kernel.md + tier1_navmap.md — tiered prompt injection
    for tier_file in ("tier0_kernel.md", "tier1_navmap.md"):
        tier_dest = aipass_dir / tier_file
        if not tier_dest.exists() and aipass_home:
            tier_src = Path(aipass_home) / ".aipass" / tier_file
            if tier_src.is_file():
                shutil.copy2(str(tier_src), str(tier_dest))
                created.append(str(tier_dest))

    # 2b. .aipass/hooks.json — project hook config from template
    hooks_json_path = aipass_dir / "hooks.json"
    if not hooks_json_path.exists() and aipass_home:
        template = Path(aipass_home) / ".aipass" / "project_hooks.json"
        if template.is_file():
            shutil.copy2(str(template), str(hooks_json_path))
            created.append(str(hooks_json_path))
            _enroll_project(target)
        else:
            logger.info("hooks template not found at %s — skipping", template)

    # 3-5. CLAUDE.md, AGENTS.md — project templates or AIPass source
    for md_name in ("CLAUDE.md", "AGENTS.md"):
        dest = target / md_name
        if dest.exists():
            continue
        template = Path(aipass_home) / ".aipass" / f"project_{md_name}" if aipass_home else None
        if template and template.is_file():
            content = template.read_text(encoding="utf-8").replace("{name}", name)
            dest.write_text(content, encoding="utf-8")
            created.append(str(dest))
        elif md_name == "AGENTS.md":
            dest.write_text(sc.agents_md(name), encoding="utf-8")
            created.append(str(dest))
        else:
            source = Path(aipass_home) / md_name if aipass_home else None
            if source and source.is_file():
                shutil.copy2(str(source), str(dest))
                created.append(str(dest))
            else:
                logging.getLogger(__name__).warning("Source %s not found at AIPASS_HOME, skipping", md_name)

    # 6. README.md
    readme_md_path = target / "README.md"
    if not readme_md_path.exists():
        readme_content = sc.readme_md(name).replace("{date}", today)
        readme_md_path.write_text(readme_content, encoding="utf-8")
        created.append(str(readme_md_path))

    # 7. .gitignore
    gitignore_path = target / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(sc.gitignore(), encoding="utf-8")
        created.append(str(gitignore_path))

    # 9. .claude/settings.json — tracked, permissions only (no machine-local paths)
    claude_dir = target / ".claude"
    claude_dir.mkdir(exist_ok=True)

    settings_path = claude_dir / "settings.json"
    if not settings_path.exists():
        settings_path.write_text(_claude_settings(), encoding="utf-8")
        created.append(str(settings_path))

    # 9b. .claude/settings.local.json — machine-local AIPASS_HOME (gitignored)
    if aipass_home and not is_throwaway_path(aipass_home):
        local_settings_path = claude_dir / "settings.local.json"
        if not local_settings_path.exists():
            local_settings_path.write_text(
                _claude_local_settings(aipass_home, nested=is_projects_child(target)), encoding="utf-8"
            )
            created.append(str(local_settings_path))

    # 9c. .claude/commands/prep.md — /prep session wrap-up slash command
    # Only prep.md here — memo.md belongs at provider level (~/.claude/commands/)
    commands_dir = claude_dir / "commands"
    commands_dir.mkdir(exist_ok=True)
    prep_path = commands_dir / "prep.md"
    if not prep_path.exists():
        prep_path.write_text(sc.prep_md(), encoding="utf-8")
        created.append(str(prep_path))

    # 10. src/<project>/ package structure (pip-installable from day one)
    package_name = raw_name.lower().replace("-", "_").replace(" ", "_")
    src_dir = target / "src"
    src_dir.mkdir(exist_ok=True)
    package_dir = src_dir / package_name
    if not package_dir.exists():
        package_dir.mkdir(parents=True)
        created.append(str(package_dir))
    init_py = package_dir / "__init__.py"
    if not init_py.exists():
        init_py.write_text(f'"""{raw_name} — created with aipass init."""\n', encoding="utf-8")
        created.append(str(init_py))

    # 10b. pyproject.toml — pytest config + package metadata
    pyproject_path = target / "pyproject.toml"
    if not pyproject_path.exists():
        pyproject_path.write_text(
            f'[project]\nname = "{package_name}"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n\n'
            f'[tool.pytest.ini_options]\ntestpaths = ["src"]\npythonpath = ["src"]\n',
            encoding="utf-8",
        )
        created.append(str(pyproject_path))

    # 10c. tests/ directory with conftest
    tests_dir = package_dir / "tests"
    if not tests_dir.exists():
        tests_dir.mkdir(parents=True)
        conftest = tests_dir / "conftest.py"
        conftest.write_text('"""Pytest fixtures for ' + raw_name + '."""\n', encoding="utf-8")
        created.append(str(tests_dir))

    # 11. .venv symlink → AIPass shared runtime
    venv_link = target / ".venv"
    if not venv_link.exists() and aipass_home:
        aipass_venv = Path(aipass_home) / ".venv"
        if aipass_venv.is_dir():
            venv_link.symlink_to(aipass_venv)
            created.append(f".venv (symlink to AIPass runtime: {aipass_venv})")

    return {
        "registry_id": registry_id,
        "registry_file": registry_filename,
        "project_name": name,
        "target": str(target),
        "created_files": created,
        "aipass_home": aipass_home,
    }


def update_project(target: Path) -> dict:
    """Update managed scaffold files in an existing AIPass project.

    Overwrites managed prompt and config files with the latest templates while
    leaving all user-owned files (registry, README, .gitignore,
    src/) untouched.

    Args:
        target: Directory containing the AIPass project to update.

    Returns:
        dict with project_name, target, updated_files, skipped_files.

    Raises:
        ValueError: If no ``*_REGISTRY.json`` is found in target (not an AIPass
            project or init has not been run yet).
    """
    target = target.resolve()

    # Guard: refuse to update the AIPass source repo itself. The source repo
    # has hand-maintained production files that must not be overwritten with
    # generic templates. External projects created via `aipass init` are fine.
    if (target / "src" / "aipass").is_dir() and (target / "pyproject.toml").exists():
        raise ValueError(
            "Cannot update the AIPass source repository — its files are hand-maintained, not template-generated"
        )

    # Locate the project registry to confirm this is an AIPass project and
    # derive the project name without parsing JSON (filename encodes the name).
    registry_files = list(target.glob("*_REGISTRY.json"))
    if not registry_files:
        raise ValueError("No AIPass project found — run 'aipass init' first")
    registry_path = registry_files[0]
    name = registry_path.stem.replace("_REGISTRY", "")

    updated: list[str] = []
    already_current: list[str] = []
    skipped: list[str] = []
    removed: list[str] = []
    aipass_home: str | None = None
    trust_enrolled = False

    # Managed directories — create if missing (graceful recovery).
    aipass_dir = target / ".aipass"
    aipass_dir.mkdir(exist_ok=True)

    claude_dir = target / ".claude"
    claude_dir.mkdir(exist_ok=True)

    # --- Managed files: write only when content has changed ---

    aipass_home = aipass_home or _detect_aipass_home()

    # tier0_kernel.md + tier1_navmap.md — tiered prompt injection
    for tier_file in ("tier0_kernel.md", "tier1_navmap.md"):
        tier_dest = aipass_dir / tier_file
        tier_src = Path(aipass_home) / ".aipass" / tier_file if aipass_home else None
        if tier_src and tier_src.is_file():
            canonical = tier_src.read_text(encoding="utf-8")
            if not tier_dest.exists() or tier_dest.read_text(encoding="utf-8") != canonical:
                tier_dest.write_text(canonical, encoding="utf-8")
                updated.append(str(tier_dest))
            else:
                already_current.append(str(tier_dest))
        elif tier_dest.exists():
            already_current.append(str(tier_dest))

    # settings.json — smart merge: preserve user hooks, update AIPass permissions.
    # AIPASS_HOME never lives here — machine-local paths go in settings.local.json.
    settings_path = claude_dir / "settings.json"
    if not settings_path.exists():
        settings_path.write_text(_claude_settings(), encoding="utf-8")
        updated.append(str(settings_path))
    else:
        existing_content = settings_path.read_text(encoding="utf-8")
        try:
            existing = json.loads(existing_content)
        except json.JSONDecodeError as exc:
            logger.info("settings.json parse failed, rebuilding: %s", exc)
            existing = {}
        generated = json.loads(_claude_settings())
        merged = _merge_settings(existing, generated)
        merged_content = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
        if existing != merged:
            settings_path.write_text(merged_content, encoding="utf-8")
            updated.append(str(settings_path))
        else:
            already_current.append(str(settings_path))

    # settings.local.json (gitignored) — machine-local AIPASS_HOME + claudeMdExcludes
    # fence. Retrofit-safe: merges into existing content, never clobbers.
    if aipass_home and not is_throwaway_path(aipass_home):
        local_settings_path = claude_dir / "settings.local.json"
        generated = json.loads(_claude_local_settings(aipass_home, nested=is_projects_child(target)))
        if not local_settings_path.exists():
            local_settings_path.write_text(json.dumps(generated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            updated.append(str(local_settings_path))
        else:
            existing_content = local_settings_path.read_text(encoding="utf-8")
            try:
                existing = json.loads(existing_content)
            except json.JSONDecodeError as exc:
                logger.info("settings.local.json parse failed, rebuilding: %s", exc)
                existing = {}
            merged = _merge_local_settings(existing, generated)
            if existing != merged:
                local_settings_path.write_text(
                    json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                updated.append(str(local_settings_path))
            else:
                already_current.append(str(local_settings_path))

    # hooks.json — union-merge: preserve user enabled, add new hooks from template
    hooks_json_path = aipass_dir / "hooks.json"
    hook_home = aipass_home or _detect_aipass_home()
    template_path = Path(hook_home) / ".aipass" / "project_hooks.json" if hook_home else None
    if template_path and template_path.is_file():
        template_data = json.loads(template_path.read_text(encoding="utf-8"))
        if hooks_json_path.exists():
            try:
                existing_hooks = json.loads(hooks_json_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                logger.info("hooks.json parse failed, rebuilding: %s", exc)
                existing_hooks = {}
            merged_hooks = _merge_hooks_json(existing_hooks, template_data)
            merged_hooks_content = json.dumps(merged_hooks, indent=2, ensure_ascii=False) + "\n"
            if existing_hooks != merged_hooks:
                hooks_json_path.write_text(merged_hooks_content, encoding="utf-8")
                updated.append(str(hooks_json_path))
                trust_enrolled = _enroll_project(target)
            else:
                already_current.append(str(hooks_json_path))
        else:
            hooks_json_path.write_text(
                json.dumps(template_data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            updated.append(str(hooks_json_path))
            trust_enrolled = _enroll_project(target)
    elif hooks_json_path.exists():
        already_current.append(str(hooks_json_path))

    # CLAUDE.md, AGENTS.md — sync from project templates or AIPass source
    for md_name in ("CLAUDE.md", "AGENTS.md"):
        dest = target / md_name
        template = Path(aipass_home) / ".aipass" / f"project_{md_name}" if aipass_home else None
        if template and template.is_file():
            new_content = template.read_text(encoding="utf-8").replace("{name}", name)
            if not dest.exists() or dest.read_text(encoding="utf-8") != new_content:
                dest.write_text(new_content, encoding="utf-8")
                updated.append(str(dest))
            else:
                already_current.append(str(dest))
        else:
            already_current.append(str(dest))

    # .claude/commands/prep.md — managed slash command, refresh to latest
    # Only prep.md — memo.md belongs at provider level (~/.claude/commands/)
    commands_dir = claude_dir / "commands"
    commands_dir.mkdir(exist_ok=True)
    prep_path = commands_dir / "prep.md"
    generated = sc.prep_md()
    if not prep_path.exists() or prep_path.read_text(encoding="utf-8") != generated:
        prep_path.write_text(generated, encoding="utf-8")
        updated.append(str(prep_path))
    else:
        already_current.append(str(prep_path))

    # --- User-owned files: always skip ---
    for skip_name in (
        str(registry_path),
        str(target / "README.md"),
        str(target / ".gitignore"),
    ):
        skipped.append(skip_name)

    # .venv symlink → AIPass shared runtime (create if missing)
    venv_link = target / ".venv"
    if not venv_link.exists() and aipass_home:
        aipass_venv = Path(aipass_home) / ".venv"
        if aipass_venv.is_dir():
            venv_link.symlink_to(aipass_venv)
            updated.append(f".venv (symlink to AIPass runtime: {aipass_venv})")

    # --- Cruft cleanup: remove known-stale AIPass-managed artifacts ---
    for rel in _STALE_MANAGED_FILES:
        stale_path = target / rel
        if stale_path.is_file():
            stale_path.unlink()
            removed.append(str(stale_path))
            logger.info("Removed stale managed file: %s", stale_path)

    return {
        "project_name": name,
        "target": str(target),
        "updated_files": updated,
        "already_current": already_current,
        "skipped_files": skipped,
        "removed_files": removed,
        "aipass_home": aipass_home,
        "trust_enrolled": trust_enrolled,
    }
