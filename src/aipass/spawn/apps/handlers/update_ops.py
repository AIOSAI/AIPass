# =================== AIPass ====================
# Name: update_ops.py
# Description: Update handler — path-based template sync engine (P1 rewrite, TDPLAN-0006)
# Version: 2.4.0
# Created: 2026-03-07
# Modified: 2026-10-24
# =============================================

"""Update handler — path-based template sync engine.

Reference: docs/update_engine.md
"""

import json
import shutil
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.aipass.shared.json_ops import backup_json, deep_merge
from aipass.spawn.apps.handlers.class_registry import get_template_dir, resolve_template_class
from aipass.spawn.apps.handlers.meta_ops import (
    generate_branch_meta,
    load_template_registry,
    save_branch_meta,
)
from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.file_ops import SKIP_NAMES
from aipass.spawn.apps.handlers.placeholders import build_replacements_dict, replace_placeholders
from aipass.spawn.apps.handlers.registry import find_registry, load_registry, branches_as_list
from aipass.spawn.apps.handlers.update_ignore import IGNORE_NAME, is_ignored, read_ignore
from aipass.spawn.apps.handlers.json import json_handler

# .ai_mail.local/ is @ai_mail's live mailbox: any write races a message arriving between read and write.
_NEVER_UPDATE_PREFIXES = (".trinity/", ".ai_mail.local/")
_NEVER_UPDATE_FILES = frozenset(
    {
        "DASHBOARD.local.json",
        "artifacts/birth_certificate.json",
        ".seedgo/bypass.json",
        # The .py skip only covers existing files; a deleted scaffold test must not come back.
        "tests/test_scaffold.py",
    }
)
# A file below either name is handed in when absent and never judged after.
_SANDBOX_DIRS = frozenset({"dropbox", ".archive"})
# .template_registry.json is already in SKIP_NAMES.
_SKIP_TRACKING = frozenset({".spawn/.branch_meta.json"})

# deep_merge keeps a non-empty existing list whole. Lists named here are spawn's own machinery and
# grow by the template's new entries; every other list stays existing-wins. Permissions are NOT
# template-owned: @devpulse deliberately carries fewer deny rules, and a union would re-deny it.
_TEMPLATE_OWNED_LISTS: dict[str, tuple[str, ...]] = {
    ".spawn/.registry_ignore.json": ("ignore_files", "ignore_patterns", "patterns"),
}

# The one .trinity/ file that heals; every other stays create-only under _NEVER_UPDATE_PREFIXES.
_PASSPORT_HEAL_PATH = ".trinity/passport.json"

# Only these reach an existing passport; a 2.0-only field here would half-migrate every 1.0 passport.
_PASSPORT_HEAL_ALLOWLIST = (
    ("branch_info", "email"),
    ("branch_info", "git_branch"),
    ("identity", "traits"),
)


def _is_never_update(resolved_path: str) -> bool:
    """Check if a resolved path is in the create-only set."""
    if resolved_path in _NEVER_UPDATE_FILES:
        return True
    for prefix in _NEVER_UPDATE_PREFIXES:
        if resolved_path.startswith(prefix):
            return True
    return False


def update_branch(
    branch_name: str,
    dry_run: bool = False,
    trace: bool = False,
    registry_path: Path | str | None = None,
) -> dict:
    """Update a single branch from its class template.

    registry_path None walks up from the CWD; adoption passes its own so a same-named branch elsewhere
    is never reached. Raises UpdateIgnoreUnreadable before any write.
    """
    errors: list[str] = []
    counts = {
        "additions": 0,
        "renames": 0,
        "updates": 0,
        "pruned": 0,
        "skipped_py": 0,
        "owner_protected": 0,
        "md_matches": 0,
        "md_differs": 0,
        "md_unreadable": 0,
    }
    additions_detail: list[dict] = []
    updates_detail: list[dict] = []
    ignored_detail: list[dict] = []
    md_detail: list[dict] = []

    branch_dir = _resolve_branch_path(branch_name, registry_path)
    if branch_dir is None:
        return _result(branch_name, False, counts, [f"Branch '{branch_name}' not found in registry"], dry_run)
    if not branch_dir.is_dir():
        return _result(branch_name, False, counts, [f"Branch directory does not exist: {branch_dir}"], dry_run)

    if trace:
        logger.info("[update] Resolved %s -> %s", branch_name, branch_dir)

    identity = _read_identity(branch_dir)
    citizen_class = identity["citizen_class"]
    template_dir = get_template_dir(citizen_class)

    if not template_dir.is_dir():
        return _result(branch_name, False, counts, [f"Template directory not found: {template_dir}"], dry_run)

    if trace:
        logger.info("[update] Citizen class: %s, template: %s", citizen_class, template_dir)

    replacements = build_replacements_dict(branch_dir, branch_name, citizen_class=citizen_class)
    # Free text renders into the read-only .md preview only: a quote in it would break every template JSON parse.
    md_replacements = {**replacements, "PURPOSE_BRIEF": identity.get("purpose") or replacements["PURPOSE_BRIEF"]}

    # Checked before every other rule in both walks: nothing downstream may reconsider the owner's call.
    ignore_patterns = read_ignore(branch_dir)
    if ignore_patterns and trace:
        logger.info("[update] %s declares %d owner-protected pattern(s)", IGNORE_NAME, len(ignore_patterns))

    for template_subdir in sorted(template_dir.rglob("*")):
        if not template_subdir.is_dir():
            continue
        if SKIP_NAMES.intersection(template_subdir.relative_to(template_dir).parts):
            continue
        rel_dir = template_subdir.relative_to(template_dir).as_posix()
        resolved_dir = replace_placeholders(rel_dir, replacements)
        if is_ignored(resolved_dir, ignore_patterns):
            if trace:
                logger.info("[update] SKIP (%s): %s/", IGNORE_NAME, resolved_dir)
            continue
        if _is_never_update(resolved_dir + "/"):
            continue
        dest_dir = branch_dir / resolved_dir
        if not dest_dir.exists():
            if not dry_run:
                dest_dir.mkdir(parents=True, exist_ok=True)
            additions_detail.append({"template_path": resolved_dir, "type": "directory"})
            counts["additions"] += 1
            if trace:
                logger.info("[update] Added directory: %s", resolved_dir)

    for template_file in sorted(template_dir.rglob("*")):
        if not template_file.is_file():
            continue
        if SKIP_NAMES.intersection(template_file.relative_to(template_dir).parts):
            continue

        rel_path = template_file.relative_to(template_dir).as_posix()

        if rel_path in _SKIP_TRACKING:
            continue

        resolved_path = replace_placeholders(rel_path, replacements)

        if is_ignored(resolved_path, ignore_patterns):
            # Must run before the passport heal below can propose a merge.
            ignored_detail.append({"branch_path": resolved_path})
            counts["owner_protected"] += 1
            if trace:
                logger.info("[update] SKIP (%s): %s", IGNORE_NAME, resolved_path)
            continue

        if resolved_path == _PASSPORT_HEAL_PATH:
            dest = branch_dir / resolved_path
            if dest.exists():
                result = _heal_passport(
                    template_file, dest, replacements, dry_run, trace, branch_dir / ".spawn" / ".recovery"
                )
                if result == "updated":
                    counts["updates"] += 1
                    updates_detail.append({"template_path": rel_path, "branch_path": resolved_path})
                elif result == "error":
                    errors.append(f"Passport heal failed for {resolved_path}")
            elif trace:
                logger.info("[update] SKIP (no passport to heal): %s", resolved_path)
            continue

        if _is_never_update(resolved_path):
            if trace:
                logger.info("[update] SKIP (create-only): %s", resolved_path)
            continue

        dest = branch_dir / resolved_path

        if not dest.exists():
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    content = template_file.read_text(encoding="utf-8")
                    content = replace_placeholders(content, replacements)
                    atomic_write_text(dest, content)
                except (UnicodeDecodeError, UnicodeEncodeError) as enc_err:
                    logger.warning("[update] Binary file, copying directly: %s (%s)", resolved_path, enc_err)
                    shutil.copy2(template_file, dest)
            additions_detail.append({"template_path": resolved_path, "type": "file"})
            counts["additions"] += 1
            if dest.suffix == ".md":
                md_detail.append({"branch_path": resolved_path, "state": "absent"})
            if trace:
                logger.info("[update] Added: %s", resolved_path)

        elif _SANDBOX_DIRS.intersection(PurePosixPath(resolved_path).parts[:-1]):
            # Parts below the branch root only: the branch itself may live under a dir named dropbox.
            if trace:
                logger.info("[update] SKIP (sandbox): %s", resolved_path)

        elif dest.suffix == ".md":
            # Read-only, always: .md content is the owner's judgment; update reports, never writes.
            state = _md_state(template_file, dest, md_replacements)
            counts[f"md_{state}"] += 1
            md_detail.append({"branch_path": resolved_path, "state": state})
            if trace:
                logger.info("[update] .md %s: %s", state, resolved_path)

        elif dest.suffix == ".py":
            counts["skipped_py"] += 1
            updates_detail.append({"template_path": rel_path, "branch_path": resolved_path})
            if trace:
                logger.info("[update] SKIP .py: %s", resolved_path)

        elif dest.suffix == ".json":
            result = _merge_json(
                template_file,
                dest,
                replacements,
                dry_run,
                trace,
                branch_dir / ".spawn" / ".recovery",
                resolved_path,
            )
            if result == "updated":
                counts["updates"] += 1
                updates_detail.append({"template_path": rel_path, "branch_path": resolved_path})
            elif result == "error":
                errors.append(f"JSON merge failed for {resolved_path}")

    if not dry_run:
        template_registry = load_template_registry(template_dir)
        if template_registry:
            updated_meta = generate_branch_meta(branch_dir, template_registry)
            updated_meta["metadata"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
            save_branch_meta(branch_dir, updated_meta)

    success = len(errors) == 0
    if success and not dry_run:
        json_handler.log_operation("update_executed", data={"branch": branch_name})

    return _result(
        branch_name,
        success,
        counts,
        errors,
        dry_run,
        _additions_detail=additions_detail,
        _updates_detail=updates_detail,
        _renames_detail=[],
        _pruned_detail=[],
        _ignored_detail=ignored_detail,
        _md_detail=md_detail,
    )


def _failed_row(branch: str, exc: Exception, dry_run: bool) -> dict:
    """The result row of a branch update_all could not update."""
    return {
        "branch": branch,
        "success": False,
        "additions": 0,
        "renames": 0,
        "updates": 0,
        "pruned": 0,
        "skipped_py": 0,
        "errors": [str(exc)],
        "dry_run": dry_run,
    }


def update_all(dry_run: bool = False, trace: bool = False, citizen_class: str | None = None) -> list[dict]:
    """Update all branches from AIPASS_REGISTRY.json, skipping spawn itself, optionally by class."""
    registry_path = find_registry()
    if registry_path is None:
        logger.error("[update] No *_REGISTRY.json found above the current directory — no branches to update")
        return []
    registry = load_registry(registry_path)
    branches = branches_as_list(registry.get("branches", []))

    if not branches:
        return []

    results: list[dict] = []

    for branch_entry in branches:
        name = branch_entry.get("name", "")
        lower_name = name.lower()

        if lower_name == "spawn":
            if trace:
                logger.info("[update] Skipping spawn (self)")
            continue

        if citizen_class:
            branch_dir = _resolve_branch_path(lower_name)
            if branch_dir and branch_dir.is_dir():
                try:
                    actual_class = _read_citizen_class(branch_dir)
                except (OSError, ValueError) as exc:
                    logger.error("[update] Cannot read the class of %s: %s", name, exc)
                    results.append(_failed_row(lower_name, exc, dry_run))
                    continue
                if actual_class != citizen_class:
                    if trace:
                        logger.info("[update] Skipping %s (class=%s, filter=%s)", name, actual_class, citizen_class)
                    continue

        if trace:
            logger.info("[update] Processing branch: %s", name)

        try:
            result = update_branch(lower_name, dry_run=dry_run, trace=trace)
            results.append(result)
        except Exception as exc:
            logger.error("[update] Error updating %s: %s", name, exc)
            results.append(_failed_row(lower_name, exc, dry_run))

    return results


def _read_citizen_class(branch_dir: Path) -> str:
    """Read a branch's passport.json and resolve it to a template class (raises as _read_identity)."""
    return _read_identity(branch_dir)["citizen_class"]


def _read_identity(branch_dir: Path) -> dict:
    """Read a branch passport's identity block, its citizen_class resolved to a template class.

    No fallback: a missing, corrupt, unknown-class or retired-class passport raises, naming the path.
    """
    passport_path = branch_dir / ".trinity" / "passport.json"
    if not passport_path.exists():
        raise FileNotFoundError(f"No passport.json at {passport_path} — cannot resolve template class.")

    try:
        data = json.loads(passport_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError) as e:
        raise ValueError(f"Corrupt or unreadable passport.json at {passport_path}: {e}") from e

    identity = data.get("identity", {})
    try:
        return {**identity, "citizen_class": resolve_template_class(identity)}
    except ValueError as e:
        raise ValueError(f"{e} (passport: {passport_path})") from e


def _resolve_branch_path(branch_name: str, registry_path: Path | str | None = None) -> Path | None:
    """Resolve a branch name to its absolute directory path via the registry (None: CWD walk)."""
    registry_path = Path(registry_path) if registry_path else find_registry()
    if registry_path is None:
        logger.info("[update] No *_REGISTRY.json found — cannot resolve a branch path without one")
        return None
    project_root = registry_path.parent
    registry = load_registry(registry_path)

    for branch in branches_as_list(registry.get("branches", [])):
        reg_name = branch.get("name", "")
        if reg_name.lower() == branch_name.lower():
            rel_path = branch.get("path", "")
            if rel_path:
                return (project_root / rel_path).resolve()

    return None


def _heal_passport(
    template_file: Path,
    dest: Path,
    replacements: dict,
    dry_run: bool,
    trace: bool,
    backup_dest: Path | None = None,
) -> str:
    """Heal an existing passport.json against the allowlist only (DPLAN-0262).

    Field by field in place, so a healthy passport is byte-for-byte unchanged. identity.traits is
    free text: an existing value (even "") stays; a legacy top-level traits array moves into it.
    Returns "updated", "unchanged", or "error".
    """
    try:
        template_content = template_file.read_text(encoding="utf-8")
        template_content = replace_placeholders(template_content, replacements)
        template_data = json.loads(template_content)

        existing_text = dest.read_text(encoding="utf-8")
        existing_data = json.loads(existing_text)
        # Compare documents, not text: an ensure_ascii=True file never matches this re-serialisation.
        original_document = json.loads(existing_text)

        legacy_traits = existing_data.pop("traits", None)

        for section, key in _PASSPORT_HEAL_ALLOWLIST:
            section_data = existing_data.setdefault(section, {})
            if (section, key) == ("identity", "traits"):
                if legacy_traits is not None and not section_data.get(key):
                    section_data[key] = legacy_traits
                elif key not in section_data:
                    section_data[key] = template_data.get(section, {}).get(key)
                continue
            template_value = template_data.get(section, {}).get(key)
            section_data[key] = deep_merge(template_value, section_data.get(key))

        merged_text = json.dumps(existing_data, indent=2, ensure_ascii=False) + "\n"

        if existing_data == original_document:
            if trace:
                logger.info("[update] Passport unchanged: %s", dest)
            return "unchanged"

        if not dry_run:
            backup_json(dest, backup_dir=backup_dest)
            atomic_write_text(dest, merged_text)

        if trace:
            logger.info("[update] Passport healed: %s", dest)
        return "updated"

    except (json.JSONDecodeError, IOError) as exc:
        logger.error("[update] Passport heal failed for %s: %s", dest, exc)
        return "error"


def _grow_template_owned_lists(merged: dict, template_data: dict, dotted_keys: tuple[str, ...]) -> None:
    """Append template list entries the branch is missing, in place.

    Grown, never reordered or pruned; an entry a branch removed does come back — that is template-owned."""
    for dotted in dotted_keys:
        section: Any = merged
        template_section: Any = template_data
        parts = dotted.split(".")
        for part in parts[:-1]:
            if not isinstance(section, dict) or not isinstance(template_section, dict):
                break
            section = section.get(part)
            template_section = template_section.get(part)
        leaf = parts[-1]
        if not isinstance(section, dict) or not isinstance(template_section, dict):
            continue
        existing_list = section.get(leaf)
        template_list = template_section.get(leaf)
        if not isinstance(existing_list, list) or not isinstance(template_list, list):
            continue
        section[leaf] = existing_list + [item for item in template_list if item not in existing_list]


def _md_state(template_file: Path, dest: Path, replacements: dict) -> str:
    """Compare a branch .md against what the template would render, writing nothing.

    Returns "matches", "differs", or "unreadable" (its own answer, never a guessed "differs")."""
    try:
        rendered = replace_placeholders(template_file.read_text(encoding="utf-8"), replacements)
        current = dest.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("[update] .md unreadable, not compared: %s (%s)", dest, exc)
        return "unreadable"
    return "matches" if rendered == current else "differs"


def _merge_json(
    template_file: Path,
    dest: Path,
    replacements: dict,
    dry_run: bool,
    trace: bool,
    backup_dest: Path | None = None,
    resolved_path: str = "",
) -> str:
    """Deep-merge a template JSON file into the branch copy.

    ``resolved_path`` selects the _TEMPLATE_OWNED_LISTS policy. Returns "updated", "unchanged", or "error".
    """
    try:
        template_content = template_file.read_text(encoding="utf-8")
        template_content = replace_placeholders(template_content, replacements)
        template_data = json.loads(template_content)

        existing_text = dest.read_text(encoding="utf-8")
        existing_data = json.loads(existing_text)

        merged = deep_merge(template_data, existing_data)
        owned_lists = _TEMPLATE_OWNED_LISTS.get(resolved_path)
        if owned_lists and isinstance(merged, dict) and isinstance(template_data, dict):
            _grow_template_owned_lists(merged, template_data, owned_lists)
        merged_text = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"

        # Documents, not text: key order or escaping alone must not rewrite and back up every run.
        if merged == existing_data:
            if trace:
                logger.info("[update] JSON unchanged: %s", dest.name)
            return "unchanged"

        if not dry_run:
            backup_json(dest, backup_dir=backup_dest)
            atomic_write_text(dest, merged_text)

        if trace:
            logger.info("[update] JSON merged: %s", dest.name)
        return "updated"

    except (json.JSONDecodeError, IOError) as exc:
        logger.error("[update] JSON merge failed for %s: %s", dest.name, exc)
        return "error"


def _result(
    branch_name: str,
    success: bool,
    counts: dict,
    errors: list[str],
    dry_run: bool,
    **extra: Any,
) -> dict:
    """Build a standardized result dict."""
    result = {
        "branch": branch_name,
        "success": success,
        "additions": counts.get("additions", 0),
        "renames": counts.get("renames", 0),
        "updates": counts.get("updates", 0),
        "pruned": counts.get("pruned", 0),
        "skipped_py": counts.get("skipped_py", 0),
        "owner_protected": counts.get("owner_protected", 0),
        "md_matches": counts.get("md_matches", 0),
        "md_differs": counts.get("md_differs", 0),
        "md_unreadable": counts.get("md_unreadable", 0),
        "errors": errors,
        "dry_run": dry_run,
    }
    result.update(extra)
    return result
