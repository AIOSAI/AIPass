# =================== AIPass ====================
# Name: bootstrap.py
# Description: Init handler — bootstrap an AIPass project in any directory
# Version: 2.0.3
# Created: 2026-03-14
# Modified: 2026-10-17
# =============================================

"""
Init Bootstrap Handler - PRIVATE implementation

Projects are not citizens (no .trinity/); identity lives in the registry JSON.
Init is re-runnable: existing files are skipped, not errors. No module/prax/cli imports.
"""

import json
import logging
import re
import shutil
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from aipass.aipass.apps.handlers.init import scaffold_manifest as sm
from aipass.aipass.shared import scaffold_content as sc
from aipass.aipass.shared.project_home import (
    claude_local_settings,
    _claude_settings,
    _detect_aipass_home,
    _enroll_project,
    merge_local_settings,
    is_projects_child,
    is_throwaway_path,
)
from aipass.aipass.shared.registry_discovery import registries_in

logger = logging.getLogger(__name__)

_STALE_MANAGED_FILES: list[Path] = [
    Path(".aipass") / "aipass_global_prompt.md",
]

#: Scaffold files the manifest hashes, in plan display order; the rest of the tree is the project's.
_MANIFEST_TRACKED: tuple = (
    ".aipass/tier0_kernel.md",
    ".aipass/tier1_navmap.md",
    ".aipass/hooks.json",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/commands/prep.md",
    "CLAUDE.md",
    "AGENTS.md",
)


def _sanitize_name(raw: str) -> str:
    """Sanitize a project name for use in filenames."""
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

    The provider owns hooks now: strip previously-injected AIPass hooks, keep user hooks.
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

    # AIPASS_HOME is machine-local (settings.local.json) and must never stay in the tracked file.
    existing_env = {k: v for k, v in existing.get("env", {}).items() if k != "AIPASS_HOME"}
    if existing_env:
        merged["env"] = existing_env

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

    *allow_projects_child* skips the nested-project checks for ``<host>/projects/<name>`` (``aipass new``).
    """
    target = target.resolve()
    if (target / ".trinity" / "passport.json").is_file():
        raise RuntimeError(
            f"BLOCKED: '{target}' is an agent branch (has .trinity/passport.json). "
            "Agents are managed by 'drone @spawn', not 'aipass init'."
        )
    for parent in target.parents:
        if (parent / ".trinity" / "passport.json").is_file():
            raise RuntimeError(
                f"BLOCKED: '{target}' is inside agent branch '{parent.name}'. "
                "Cannot run aipass init inside an agent directory."
            )
        if parent == parent.parent:
            break
    for f in target.iterdir() if target.is_dir() else []:
        if f.is_file() and f.name.endswith("_REGISTRY.json"):
            if allow_projects_child and is_projects_child(target):
                break
            raise RuntimeError(
                f"BLOCKED: '{target}' is already an AIPass project (has {f.name}). "
                "Use 'aipass init update' to upgrade an existing project."
            )
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

    Raises ValueError on an empty sanitized name, RuntimeError inside a branch or project.
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

    registry_filename = f"{name}_REGISTRY.json"
    registry_path = target / registry_filename
    if registry_path.exists():
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
        sm.write_text_lf(registry_path, json.dumps(registry_data, indent=2, ensure_ascii=False) + "\n")
        created.append(str(registry_path))

    aipass_dir = target / ".aipass"
    aipass_dir.mkdir(exist_ok=True)

    for tier_file in ("tier0_kernel.md", "tier1_navmap.md"):
        tier_dest = aipass_dir / tier_file
        if not tier_dest.exists() and aipass_home:
            tier_src = Path(aipass_home) / ".aipass" / tier_file
            if tier_src.is_file():
                # Not copy2: a CRLF checkout of AIPASS_HOME would land a hash no template comparison matches.
                sm.write_text_lf(tier_dest, tier_src.read_text(encoding="utf-8"))
                created.append(str(tier_dest))

    hooks_json_path = aipass_dir / "hooks.json"
    if not hooks_json_path.exists() and aipass_home:
        template = Path(aipass_home) / ".aipass" / "project_hooks.json"
        if template.is_file():
            sm.write_text_lf(hooks_json_path, template.read_text(encoding="utf-8"))
            created.append(str(hooks_json_path))
            _enroll_project(target)
        else:
            logger.info("hooks template not found at %s — skipping", template)

    for md_name in ("CLAUDE.md", "AGENTS.md"):
        dest = target / md_name
        if dest.exists():
            continue
        template = Path(aipass_home) / ".aipass" / f"project_{md_name}" if aipass_home else None
        if template and template.is_file():
            content = template.read_text(encoding="utf-8").replace("{name}", name)
            sm.write_text_lf(dest, content)
            created.append(str(dest))
        elif md_name == "AGENTS.md":
            sm.write_text_lf(dest, sc.agents_md(name))
            created.append(str(dest))
        else:
            source = Path(aipass_home) / md_name if aipass_home else None
            if source and source.is_file():
                sm.write_text_lf(dest, source.read_text(encoding="utf-8"))
                created.append(str(dest))
            else:
                logging.getLogger(__name__).warning("Source %s not found at AIPASS_HOME, skipping", md_name)

    readme_md_path = target / "README.md"
    if not readme_md_path.exists():
        readme_content = sc.readme_md(name).replace("{date}", today)
        sm.write_text_lf(readme_md_path, readme_content)
        created.append(str(readme_md_path))

    gitignore_path = target / ".gitignore"
    if not gitignore_path.exists():
        sm.write_text_lf(gitignore_path, sc.gitignore())
        created.append(str(gitignore_path))

    # settings.json is tracked: permissions only, machine-local paths go in settings.local.json.
    claude_dir = target / ".claude"
    claude_dir.mkdir(exist_ok=True)

    settings_path = claude_dir / "settings.json"
    if not settings_path.exists():
        sm.write_text_lf(settings_path, _claude_settings())
        created.append(str(settings_path))

    if aipass_home and not is_throwaway_path(aipass_home):
        local_settings_path = claude_dir / "settings.local.json"
        if not local_settings_path.exists():
            sm.write_text_lf(local_settings_path, claude_local_settings(aipass_home, nested=is_projects_child(target)))
            created.append(str(local_settings_path))

    # Only prep.md here: memo.md belongs at provider level (~/.claude/commands/).
    commands_dir = claude_dir / "commands"
    commands_dir.mkdir(exist_ok=True)
    prep_path = commands_dir / "prep.md"
    if not prep_path.exists():
        sm.write_text_lf(prep_path, sc.prep_md())
        created.append(str(prep_path))

    # Sanitized name, never raw: a raw one can nest a slash, carry unimportable
    # punctuation, or end in a dot Windows rejects.
    package_name = name.lower().replace("-", "_")
    src_dir = target / "src"
    src_dir.mkdir(exist_ok=True)
    package_dir = src_dir / package_name
    if not package_dir.exists():
        package_dir.mkdir(parents=True)
        created.append(str(package_dir))
    init_py = package_dir / "__init__.py"
    if not init_py.exists():
        sm.write_text_lf(init_py, f'"""{raw_name} — created with aipass init."""\n')
        created.append(str(init_py))

    pyproject_path = target / "pyproject.toml"
    if not pyproject_path.exists():
        sm.write_text_lf(
            pyproject_path,
            f'[project]\nname = "{package_name}"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n\n'
            f'[tool.pytest.ini_options]\ntestpaths = ["src"]\npythonpath = ["src"]\n',
        )
        created.append(str(pyproject_path))

    tests_dir = package_dir / "tests"
    if not tests_dir.exists():
        tests_dir.mkdir(parents=True)
        conftest = tests_dir / "conftest.py"
        sm.write_text_lf(conftest, '"""Pytest fixtures for ' + raw_name + '."""\n')
        created.append(str(tests_dir))

    venv_link = target / ".venv"
    if not venv_link.exists() and aipass_home:
        aipass_venv = Path(aipass_home) / ".venv"
        if aipass_venv.is_dir():
            venv_link.symlink_to(aipass_venv)
            created.append(f".venv (symlink to AIPass runtime: {aipass_venv})")

    # The manifest lets `init update` tell "the template moved on" from "the project edited this file".
    manifest_file = sm.write_manifest(target, _managed_manifest_entries(target))
    created.append(str(manifest_file))

    return {
        "registry_id": registry_id,
        "registry_file": registry_filename,
        "project_name": name,
        "target": str(target),
        "created_files": created,
        "aipass_home": aipass_home,
    }


def _seed_content(md_name: str, name: str, aipass_home: str | None) -> str | None:
    """Content a seed file is created with, or None when no source is available.

    Shared with update so a lost ``CLAUDE.md`` comes back as init would have minted it.
    """
    template = Path(aipass_home) / ".aipass" / f"project_{md_name}" if aipass_home else None
    if template and template.is_file():
        return template.read_text(encoding="utf-8").replace("{name}", name)
    if md_name == "AGENTS.md":
        return sc.agents_md(name)
    source = Path(aipass_home) / md_name if aipass_home else None
    if source and source.is_file():
        return source.read_text(encoding="utf-8")
    return None


def _read_text(path: Path) -> str | None:
    """Read a text file, or None when it is absent or not decodable as UTF-8."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("unreadable, treating as absent: %s (%s)", path, exc)
        return None


def _managed_manifest_entries(target: Path) -> dict:
    """Hashes of every tracked scaffold file that exists in *target*.

    Init-only: after a full write, every tracked file on disk is by definition ours.
    """
    entries: dict = {}
    for rel in _MANIFEST_TRACKED:
        digest = sm.hash_file(target / rel)
        if digest is not None:
            entries[rel] = digest
    return entries


def update_project(target: Path, *, apply: bool = True) -> dict:
    """Plan -- and optionally apply -- a scaffold update for an AIPass project.

    Plan mode (``apply=False``) performs ZERO filesystem writes (no mkdir, stamp or
    trust enrolment): ``init update --dry-run`` is only trustworthy because of it.
    """
    target = target.resolve()

    # The source repo's files are hand-maintained; templates must never overwrite them.
    if (target / "src" / "aipass").is_dir() and (target / "pyproject.toml").exists():
        raise ValueError(
            "Cannot update the AIPass source repository — its files are hand-maintained, not template-generated"
        )

    registry_files = registries_in(target)
    if not registry_files:
        raise ValueError("No AIPass project found — run 'aipass init' first")
    registry_path = registry_files[0]
    name = registry_path.stem.replace("_REGISTRY", "")

    aipass_home = _detect_aipass_home()
    recorded = sm.manifest_hashes(target)
    installed = sm.installed_version()
    stamped = sm.stamped_version(target)
    ignored = sm.read_ignore(target)

    aipass_dir = target / ".aipass"
    claude_dir = target / ".claude"

    files: list[dict] = []
    handlers: list[dict] = []
    writes: list[tuple] = []  # (destination, content) — performed only when apply
    retires: list[Path] = []
    symlinks: list[tuple] = []  # (link, destination)
    manifest_next: dict = {}
    trust_reenrol = False

    def record(rel: str, dest: Path, action: str, reason: str, content: str | None = None) -> None:
        """Add one file to the plan and queue whatever write it implies.

        ``.updateignore`` outranks the seed and hash rules: a claimed file gets no
        write, backup, sidecar or drift report.
        """
        nonlocal manifest_next
        if sm.is_ignored(rel, ignored):
            files.append({"path": rel, "action": sm.ACTION_SKIPPED, "reason": sm.IGNORE_NAME, "writes": False})
            # No manifest entry on purpose: the on-disk hash would make a later
            # un-ignore read as "unmodified" and overwrite the protected file.
            return
        writes_before = len(writes)
        if action in (sm.ACTION_CREATE, sm.ACTION_UPDATE):
            writes.append((dest, content))
            manifest_next[rel] = sm.sha256_text(content or "")
        elif action == sm.ACTION_CURRENT:
            digest = sm.hash_file(dest)
            if digest is not None:
                manifest_next[rel] = digest
        elif action == sm.ACTION_KEPT_LOCAL:
            # A sidecar already matching the template means no write; claiming
            # one would preview "would change / exit 2" forever after one apply.
            sidecar = sm.sidecar_path(dest)
            if sm.hash_file(sidecar) == sm.sha256_text(content or ""):
                reason = f"{reason} (template already beside it)"
            else:
                writes.append((sidecar, content))
            # The manifest records what AIPass wrote: adopting the edited hash
            # would let the next update overwrite the manager's edit.
            if rel in recorded:
                manifest_next[rel] = recorded[rel]
        # The plan's counts and exit code both read "writes", so they never disagree.
        files.append({"path": rel, "action": action, "reason": reason, "writes": len(writes) > writes_before})

    managed: list[tuple] = []
    for tier_file in ("tier0_kernel.md", "tier1_navmap.md"):
        src = Path(aipass_home) / ".aipass" / tier_file if aipass_home else None
        text = _read_text(src) if src and src.is_file() else None
        managed.append((f".aipass/{tier_file}", aipass_dir / tier_file, text))
    managed.append((".claude/commands/prep.md", claude_dir / "commands" / "prep.md", sc.prep_md()))

    for rel, dest, template_text in managed:
        current_hash = sm.hash_file(dest)
        template_hash = sm.sha256_text(template_text) if template_text is not None else None
        action, reason = sm.decide(current_hash, template_hash, recorded.get(rel))
        record(rel, dest, action, reason, template_text)

    for md_name in sm.SEED_FILES:
        dest = target / md_name
        if dest.exists():
            record(md_name, dest, sm.ACTION_CURRENT, "seed — never rewritten")
            continue
        content = _seed_content(md_name, name, aipass_home)
        if content is None:
            logger.warning("Source %s not found at AIPASS_HOME, skipping", md_name)
            continue
        record(md_name, dest, sm.ACTION_CREATE, "seed absent", content)

    # Merge files keep user values through the merge itself, so they are never "kept (local edits)".
    settings_path = claude_dir / "settings.json"
    generated_settings = _claude_settings()
    existing_settings_text = _read_text(settings_path)
    if existing_settings_text is None:
        record(".claude/settings.json", settings_path, sm.ACTION_CREATE, "absent", generated_settings)
    else:
        try:
            existing = json.loads(existing_settings_text)
        except json.JSONDecodeError as exc:
            logger.info("settings.json parse failed, rebuilding: %s", exc)
            existing = {}
        merged = _merge_settings(existing, json.loads(generated_settings))
        merged_content = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
        if existing != merged:
            record(
                ".claude/settings.json",
                settings_path,
                sm.ACTION_UPDATE,
                "merge adds AIPass permissions",
                merged_content,
            )
        else:
            record(".claude/settings.json", settings_path, sm.ACTION_CURRENT, "merge is a no-op")

    if aipass_home and not is_throwaway_path(aipass_home):
        local_path = claude_dir / "settings.local.json"
        generated = json.loads(claude_local_settings(aipass_home, nested=is_projects_child(target)))
        existing_local_text = _read_text(local_path)
        if existing_local_text is None:
            content = json.dumps(generated, indent=2, ensure_ascii=False) + "\n"
            record(".claude/settings.local.json", local_path, sm.ACTION_CREATE, "absent", content)
        else:
            try:
                existing = json.loads(existing_local_text)
            except json.JSONDecodeError as exc:
                logger.info("settings.local.json parse failed, rebuilding: %s", exc)
                existing = {}
            merged = merge_local_settings(existing, generated)
            merged_content = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
            if existing != merged:
                record(
                    ".claude/settings.local.json",
                    local_path,
                    sm.ACTION_UPDATE,
                    "merge adds AIPASS_HOME",
                    merged_content,
                )
            else:
                record(".claude/settings.local.json", local_path, sm.ACTION_CURRENT, "merge is a no-op")

    # Prune after the union: the union alone can only ever grow a project's hooks.
    hooks_path = aipass_dir / "hooks.json"
    template_path = Path(aipass_home) / ".aipass" / "project_hooks.json" if aipass_home else None
    if template_path and template_path.is_file():
        template_data = json.loads(template_path.read_text(encoding="utf-8"))
        existing_hooks_text = _read_text(hooks_path)
        if existing_hooks_text is None:
            existing_hooks: dict = {}
        else:
            try:
                existing_hooks = json.loads(existing_hooks_text)
            except json.JSONDecodeError as exc:
                logger.info("hooks.json parse failed, rebuilding: %s", exc)
                existing_hooks = {}
        merged_hooks = sm.prune_retired(_merge_hooks_json(existing_hooks, template_data))
        merged_hooks_content = json.dumps(merged_hooks, indent=2, ensure_ascii=False) + "\n"

        before = _handler_names(existing_hooks)
        for handler in sorted(_handler_names(merged_hooks) - before):
            handlers.append({"name": handler, "action": "add"})
        for handler in sm.retired_handlers_in(existing_hooks):
            handlers.append({"name": handler, "action": "retire"})

        if existing_hooks_text is None:
            record(".aipass/hooks.json", hooks_path, sm.ACTION_CREATE, "absent", merged_hooks_content)
            trust_reenrol = True
        elif existing_hooks != merged_hooks:
            reason = _handler_reason(handlers)
            record(".aipass/hooks.json", hooks_path, sm.ACTION_UPDATE, reason, merged_hooks_content)
            trust_reenrol = True
        else:
            record(".aipass/hooks.json", hooks_path, sm.ACTION_CURRENT, "merge is a no-op")
    elif hooks_path.exists():
        record(".aipass/hooks.json", hooks_path, sm.ACTION_CURRENT, "no template available — nothing to compare")

    # Retired managed files are renamed, never unlinked.
    for rel in _STALE_MANAGED_FILES:
        stale_path = target / rel
        if sm.is_ignored(rel.as_posix(), ignored):
            files.append(
                {"path": rel.as_posix(), "action": sm.ACTION_SKIPPED, "reason": sm.IGNORE_NAME, "writes": False}
            )
        elif stale_path.is_file():
            files.append(
                {
                    "path": rel.as_posix(),
                    "action": sm.ACTION_RETIRE,
                    "reason": f"renamed to {sm.disabled_path(stale_path).name}",
                    "writes": True,
                }
            )
            retires.append(stale_path)

    venv_link = target / ".venv"
    if not venv_link.exists() and aipass_home:
        aipass_venv = Path(aipass_home) / ".venv"
        if aipass_venv.is_dir():
            files.append(
                {
                    "path": ".venv",
                    "action": sm.ACTION_CREATE,
                    "reason": f"symlink to AIPass runtime: {aipass_venv}",
                    "writes": True,
                }
            )
            symlinks.append((venv_link, aipass_venv))

    # Tracked files with no plan entry (a merge file this host skips) keep their
    # recorded hash so a stamp never silently drops provenance.
    for rel in _MANIFEST_TRACKED:
        if sm.is_ignored(rel, ignored):
            continue
        if rel not in manifest_next and rel in recorded and (target / rel).exists():
            manifest_next[rel] = recorded[rel]

    stamp_pending = stamped != installed
    file_writes = bool(writes or retires or symlinks or handlers)
    pending = file_writes or stamp_pending
    # Stamp-only applies without a go: the receipt is the contract, and a go on a plan
    # touching no file teaches approval without reading. Same queues as ``pending``.
    stamp_only = stamp_pending and not file_writes

    # Every write in this run happens below this line.
    backup_dir: Path | None = None
    if apply:
        aipass_dir.mkdir(exist_ok=True)
        claude_dir.mkdir(exist_ok=True)
        (claude_dir / "commands").mkdir(exist_ok=True)
        backup_dir = _apply_writes(target, writes, retires, symlinks)
        sm.write_manifest(target, manifest_next, installed)
        if trust_reenrol:
            trust_reenrol = _enroll_project(target)

    updated = [str(dest) for dest, _ in writes if not dest.name.endswith(sm.NEW_SUFFIX)]
    updated += [f".venv (symlink to AIPass runtime: {dest})" for _, dest in symlinks]

    return {
        "project_name": name,
        "target": str(target),
        "aipass_home": aipass_home,
        "aipass_version": installed,
        "stamped_version": stamped,
        "stamp_pending": stamp_pending,
        "stamp_only": stamp_only,
        "applied": apply,
        "pending": pending,
        "files": files,
        "handlers": handlers,
        "trust_reenrol": trust_reenrol,
        "backup_dir": str(backup_dir) if backup_dir else None,
        # Legacy shape — the CLI and existing pins read these.
        "updated_files": updated,
        "already_current": [str(target / entry["path"]) for entry in files if entry["action"] == sm.ACTION_CURRENT],
        "kept_files": [str(target / entry["path"]) for entry in files if entry["action"] == sm.ACTION_KEPT_LOCAL],
        "ignored_files": [str(target / entry["path"]) for entry in files if entry["action"] == sm.ACTION_SKIPPED],
        "skipped_files": [
            str(registry_path),
            str(target / "README.md"),
            str(target / ".gitignore"),
        ],
        "removed_files": [str(path) for path in retires],
        "trust_enrolled": trust_reenrol,
    }


def _handler_names(hooks: dict) -> set:
    """Every handler name in a hooks document, across all events."""
    names: set = set()
    for event, entries in hooks.items():
        if isinstance(entries, dict) and event not in ("_comment", "hooks_enabled"):
            names.update(entries)
    return names


def _handler_reason(handlers: list) -> str:
    """One-line summary of the handler changes driving a hooks.json update.

    Counts, not names: the plan prints the names below, and a list here wraps the column.
    """
    added = sum(1 for h in handlers if h["action"] == "add")
    retired = sum(1 for h in handlers if h["action"] == "retire")
    parts = []
    if added:
        parts.append(f"{added} handler(s) added")
    if retired:
        parts.append(f"{retired} retired")
    return ", ".join(parts) if parts else "merge changes hook config"


def _apply_writes(target: Path, writes: list, retires: list, symlinks: list) -> Path | None:
    """Perform the planned writes, backing up anything overwritten first.

    Backups mirror the project tree under ``.aipass/.backup/scaffold_<stamp>/`` so restore is by path.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = target / sm.BACKUP_REL / f"scaffold_{stamp}"
    used = False

    def backup(path: Path) -> None:
        """Copy an existing file into the backup tree before it is replaced."""
        nonlocal used
        if not path.is_file():
            return
        dest = backup_root / path.relative_to(target)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(path), str(dest))
        used = True

    for dest, content in writes:
        # Sidecars are disposable; backing them up fills the tree with copies of copies.
        if not dest.name.endswith(sm.NEW_SUFFIX):
            backup(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        sm.write_text_lf(dest, content)

    for stale_path in retires:
        backup(stale_path)
        disabled = sm.disabled_path(stale_path)
        if disabled.exists():
            disabled.unlink()
        stale_path.rename(disabled)
        logger.info("Retired managed file: %s -> %s", stale_path, disabled)

    for link, dest in symlinks:
        link.symlink_to(dest)

    return backup_root if used else None
