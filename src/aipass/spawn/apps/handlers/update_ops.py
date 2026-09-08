# =================== AIPass ====================
# Name: update_ops.py
# Description: Update handler — path-based template sync engine (P1 rewrite, TDPLAN-0006)
# Version: 2.1.0
# Created: 2026-03-07
# Modified: 2026-07-27
# =============================================

"""Update handler — path-based template sync engine.

P1 rewrite (TDPLAN-0006, issue #636): replaces the broken ID-based
change-detection engine with explicit template walking. No renames,
no pruning, never touches identity/memory files wholesale — the one
exception is passport.json's narrow allowlist heal (DPLAN-0262), see
_PASSPORT_HEAL_ALLOWLIST.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.meta_ops import (
    generate_branch_meta,
    get_template_dir,
    load_template_registry,
    save_branch_meta,
)
from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.json_ops import backup_json, deep_merge
from aipass.spawn.apps.handlers.placeholders import build_replacements_dict, replace_placeholders
from aipass.spawn.apps.handlers.registry import find_registry, load_registry, branches_as_list
from aipass.spawn.apps.handlers.json import json_handler

# .ai_mail.local/ is a branch's live mailbox (@ai_mail's data contract, not spawn's) —
# runtime state in the same category as DASHBOARD.local.json below. update --apply
# used to deep-merge into another branch's inbox.json; no message was ever lost
# (deep_merge keeps existing scalars/non-empty lists), but the write itself was the
# problem: a message arriving between read and write could still be dropped
# (APLAN-0007 open item 2, devpulse ruling).
_NEVER_UPDATE_PREFIXES = (".trinity/", ".ai_mail.local/")
_NEVER_UPDATE_FILES = frozenset(
    {
        "DASHBOARD.local.json",
        "artifacts/birth_certificate.json",
        ".seedgo/bypass.json",
        # Scaffold smoke test — ships at create, never re-added. The .py skip below
        # only covers files that already exist, so a branch that deleted it would
        # otherwise get it back on every update. Once a branch has a real suite the
        # scaffold test can only skip, so it cannot inform (@seedgo, DPLAN-0291).
        "tests/test_scaffold.py",
    }
)
_SKIP_TRACKING = frozenset(
    {
        ".spawn/.template_registry.json",
        ".spawn/.branch_meta.json",
    }
)

# THE LIST POLICY (FPLAN-0492, 2026-09-07)
# -----------------------------------------
# deep_merge is additive for KEYS and existing-wins for VALUES, and a non-empty
# list counts as a value: an existing list is kept whole, so a list entry ADDED
# to a template after a branch was born never reaches that branch. Measured on
# @vera: the template's .registry_ignore.json grew from two ignore_files entries
# to four, and an update --apply would have left the branch at two while adding
# the notes block that describes four.
#
# Both halves of that behaviour are wanted, for different lists, so the split is
# declared by name rather than guessed:
#
#   TEMPLATE-OWNED lists (below) are additive. They are copy-engine machinery —
#   spawn writes them, spawn reads them, and a missing entry is a scaffold that
#   does not work. Template entries the branch lacks are appended; the branch's
#   own entries and their order are never touched, so a list is only ever grown.
#
#   EVERY OTHER LIST stays existing-wins, which is deep_merge's default and
#   needs no code here. That includes .claude/settings.local.json permissions:
#   they read like template-owned safety rules, and they are not. Measured
#   2026-09-07 across 18 branches, 2 differ from the template — @devpulse by 17
#   deny rules, because it is the one citizen allowed to write the repository
#   history, and @drone by 3. A union would have re-denied the fleet's only
#   publishing lane. Permission drift is a branch's own posture; it is reported
#   by hand, never merged.
_TEMPLATE_OWNED_LISTS: dict[str, tuple[str, ...]] = {
    ".spawn/.registry_ignore.json": ("ignore_files", "ignore_patterns", "patterns"),
}

# passport.json is the one .trinity/ file that heals (DPLAN-0262 fix phase) — every
# other .trinity/ file (local.json, observations.json, README.md) stays create-only
# under _NEVER_UPDATE_PREFIXES above.
_PASSPORT_HEAL_PATH = ".trinity/passport.json"

# Only these dotted (section, key) pairs are allowed to reach an existing passport.
# Identity content (role/purpose/what_i_do/what_i_dont_do), citizenship, and
# document_metadata stay create-only — a passport's voice is its own, not the
# template's, even when a field the template guarantees is missing.
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


# =============================================================================
# PUBLIC API
# =============================================================================


def update_branch(branch_name: str, dry_run: bool = False, trace: bool = False) -> dict:
    """Update a single branch from its class template.

    Path-based engine: walks the template directory, resolves placeholder
    paths, and for each file decides add/merge/skip. No renames, no pruning.
    Identity/memory files (DASHBOARD, birth_certificate, bypass.json, and all
    of .trinity/ except passport.json) are create-only. passport.json heals
    against a narrow allowlist only — see _PASSPORT_HEAL_ALLOWLIST.
    """
    errors: list[str] = []
    counts = {"additions": 0, "renames": 0, "updates": 0, "pruned": 0, "skipped_py": 0}
    additions_detail: list[dict] = []
    updates_detail: list[dict] = []

    branch_dir = _resolve_branch_path(branch_name)
    if branch_dir is None:
        return _result(branch_name, False, counts, [f"Branch '{branch_name}' not found in registry"], dry_run)
    if not branch_dir.is_dir():
        return _result(branch_name, False, counts, [f"Branch directory does not exist: {branch_dir}"], dry_run)

    if trace:
        logger.info("[update] Resolved %s -> %s", branch_name, branch_dir)

    citizen_class = _read_citizen_class(branch_dir)
    template_dir = get_template_dir(citizen_class)

    if not template_dir.is_dir():
        return _result(branch_name, False, counts, [f"Template directory not found: {template_dir}"], dry_run)

    if trace:
        logger.info("[update] Citizen class: %s, template: %s", citizen_class, template_dir)

    replacements = build_replacements_dict(branch_dir, branch_name)

    # Walk template directories — create missing ones in branch
    for template_subdir in sorted(template_dir.rglob("*")):
        if not template_subdir.is_dir():
            continue
        if "__pycache__" in template_subdir.parts:
            continue
        rel_dir = template_subdir.relative_to(template_dir).as_posix()
        resolved_dir = replace_placeholders(rel_dir, replacements)
        if _is_never_update(resolved_dir + "/"):
            continue
        if resolved_dir in _SKIP_TRACKING:
            continue
        dest_dir = branch_dir / resolved_dir
        if not dest_dir.exists():
            if not dry_run:
                dest_dir.mkdir(parents=True, exist_ok=True)
            additions_detail.append({"template_path": resolved_dir, "type": "directory"})
            counts["additions"] += 1
            if trace:
                logger.info("[update] Added directory: %s", resolved_dir)

    # Walk template files — add/merge/skip per type
    for template_file in sorted(template_dir.rglob("*")):
        if not template_file.is_file():
            continue
        if "__pycache__" in template_file.parts:
            continue

        rel_path = template_file.relative_to(template_dir).as_posix()

        if rel_path in _SKIP_TRACKING:
            continue

        resolved_path = replace_placeholders(rel_path, replacements)

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
            # ADDITION — missing file from template
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
            if trace:
                logger.info("[update] Added: %s", resolved_path)

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

    # Refresh branch metadata (informational tracking)
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
    )


def update_all(dry_run: bool = False, trace: bool = False, citizen_class: str | None = None) -> list[dict]:
    """Update all branches from AIPASS_REGISTRY.json.

    Iterates through all registered branches, calls update_branch() for each.
    Skips spawn itself (can't update yourself).
    When citizen_class is specified, only updates branches of that class.
    Returns list of result dicts.
    """
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
                actual_class = _read_citizen_class(branch_dir)
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
            results.append(
                {
                    "branch": lower_name,
                    "success": False,
                    "additions": 0,
                    "renames": 0,
                    "updates": 0,
                    "pruned": 0,
                    "skipped_py": 0,
                    "errors": [str(exc)],
                    "dry_run": dry_run,
                }
            )

    return results


# =============================================================================
# INTERNAL HELPERS
# =============================================================================


def _read_citizen_class(branch_dir: Path) -> str:
    """Read a branch's passport.json and resolve it to a template class.

    No fallback (DPLAN-0262, Patrick ruling): a missing passport, corrupt JSON, or
    unknown citizen_class is a loud hard error naming the passport path and the
    registered classes — never a silent guess at a default class. Silent defaulting
    here is exactly what let real passports drift from their template contract
    undetected for months. A passport still carrying a RETIRED class name
    ("aipass_framework", "project_agent", "builder") is refused the same way, so
    it reads as "migrate this passport" rather than updating against a class it
    no longer claims (DPLAN-0319).
    """
    from aipass.spawn.apps.handlers.class_registry import resolve_template_class

    passport_path = branch_dir / ".trinity" / "passport.json"
    if not passport_path.exists():
        raise FileNotFoundError(f"No passport.json at {passport_path} — cannot resolve template class.")

    try:
        data = json.loads(passport_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError) as e:
        raise ValueError(f"Corrupt or unreadable passport.json at {passport_path}: {e}") from e

    try:
        return resolve_template_class(data.get("identity", {}))
    except ValueError as e:
        raise ValueError(f"{e} (passport: {passport_path})") from e


def _resolve_branch_path(branch_name: str) -> Path | None:
    """Resolve a branch name to its absolute directory path via the registry."""
    registry_path = find_registry()
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

    Reuses deep_merge's scalar/list decision (additive, existing-always-wins) but
    applies it one allowlisted field at a time, mutating the field in place rather
    than rebuilding the whole dict — every other drifted or missing field (identity
    content, citizenship, document_metadata) stays exactly as create-only as it was
    before this fix, and healthy passports that already satisfy the allowlist come
    out byte-for-byte unchanged (no template-driven key reordering). email/git_branch
    fill from the template whenever missing or blank — the template always renders a
    real, derivable value for both, so there's no "custom content" to protect there.
    identity.traits is different: a hand-written template default is never a fill
    source (it's a free-text field, not a derived one), so an existing traits value —
    even "" — is left alone unless there's a legacy value to migrate. A legacy
    top-level `traits` array (devpulse, aipass — predates the identity.traits schema)
    is migrated into identity.traits rather than left to duplicate or orphan: it's
    always stripped from the top level, and only lands in identity.traits if that
    field doesn't already have real content of its own.

    Returns "updated", "unchanged", or "error".
    """
    try:
        template_content = template_file.read_text(encoding="utf-8")
        template_content = replace_placeholders(template_content, replacements)
        template_data = json.loads(template_content)

        existing_text = dest.read_text(encoding="utf-8")
        existing_data = json.loads(existing_text)
        # The document as it was, parsed independently — the "did the heal change
        # anything" question is about the DOCUMENT, not about how it was spelled on
        # disk. Comparing serialised text answered a different question and got it
        # wrong for every passport containing a non-ASCII character: those files
        # were written with escapes (\u2014) and this heal re-serialises with
        # ensure_ascii=False, so the texts never matched and an untouched passport
        # was rewritten (and backed up) on every single update. Measured on
        # @vera's 1.0.0 passport, 2026-09-07: heal returned "updated" with 120
        # bytes of diff and not one changed field.
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

    Only the keys the caller names are touched, and only when both sides really
    hold lists. Existing entries keep their position and duplicates are never
    introduced: the branch's list is grown, never reordered and never pruned —
    an entry a branch deliberately removed does come back, which is exactly what
    "the template owns this list" means and why the set is declared by name.
    """
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

    ``resolved_path`` is the branch-relative path this file lands on. It selects
    the template-owned list policy — see _TEMPLATE_OWNED_LISTS. Callers that omit
    it get deep_merge's plain existing-wins behaviour for every list.

    Returns "updated", "unchanged", or "error".
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

        if merged_text == existing_text:
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


# =============================================================================
# RESULT HELPERS
# =============================================================================


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
        "errors": errors,
        "dry_run": dry_run,
    }
    result.update(extra)
    return result
