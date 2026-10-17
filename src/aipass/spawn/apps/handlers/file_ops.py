# =================== AIPass ====================
# Name: file_ops.py
# Description: Template copy and file operations
# Version: 1.0.2
# Created: 2026-03-05
# Modified: 2026-10-17
# =============================================

"""Template copy and file rename operations."""

import hashlib
import json
import shutil
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.placeholders import replace_placeholders
from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.json import json_handler

# Tool caches belong to whoever ran the tools, never to the new branch.
SKIP_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".git", ".template_registry.json"}


def ensure_directory(path):
    """Create directory and parents if they don't exist."""
    if path is None:
        raise ValueError("ensure_directory received None path — caller passed invalid target")
    Path(path).mkdir(parents=True, exist_ok=True)


def copy_template(template_dir, target_dir, replacements):
    """Recursively copy template to target, replacing placeholders in text files."""
    template_dir = Path(template_dir)
    target_dir = Path(target_dir)
    copied = []
    skipped = []

    for item in _walk(template_dir):
        rel_path = item.relative_to(template_dir)

        # as_posix(), never str(): Windows would mix backslashes with the "/ (dir)" suffix.
        if _should_skip(rel_path):
            skipped.append(rel_path.as_posix())
            continue

        dest_rel = _replace_path_placeholders(rel_path, replacements)
        dest = target_dir / dest_rel
        listed = dest_rel.as_posix()

        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            copied.append(f"{listed}/ (dir)")
        elif item.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                logger.info(f"[spawn] Skipping existing file: {listed}")
                skipped.append(f"{listed} (exists)")
                continue
            try:
                content = item.read_text(encoding="utf-8")
                content = replace_placeholders(content, replacements)
                atomic_write_text(dest, content)
                copied.append(listed)
            except (UnicodeDecodeError, UnicodeEncodeError) as e:
                logger.warning(f"[spawn] Text read/write failed for {listed}, falling back to binary copy: {e}")
                shutil.copy2(item, dest)
                copied.append(f"{listed} (binary)")

    try:
        json_handler.log_operation("template_copied", data={"target": str(target_dir)})
    except Exception as exc:
        logger.info("json_handler.log_operation failed (non-fatal): %s", exc)

    return copied, skipped


def rename_placeholder_paths(target_dir, branch_name):
    """Rename any remaining {{BRANCH}}_json style directories and files."""
    target_dir = Path(target_dir)
    lower = branch_name.lower().replace("-", "_")
    renamed = []

    # Bottom-up, so renaming a parent does not invalidate a child's path.
    dirs_to_rename = []
    for d in sorted(target_dir.rglob("*"), reverse=True):
        if d.is_dir() and "{{BRANCH}}" in d.name:
            dirs_to_rename.append(d)

    for d in dirs_to_rename:
        new_name = d.name.replace("{{BRANCH}}", lower)
        new_path = d.parent / new_name
        if not new_path.exists():
            d.rename(new_path)
            renamed.append(f"{d.name} -> {new_name}")

    for f in target_dir.rglob("*"):
        if f.is_file() and "{{BRANCH}}" in f.name:
            new_name = f.name.replace("{{BRANCH}}", lower)
            new_path = f.parent / new_name
            if not new_path.exists():
                f.rename(new_path)
                renamed.append(f"{f.name} -> {new_name}")

    return renamed


def _walk(directory):
    """Walk directory tree including hidden files, yielding all items."""
    directory = Path(directory)
    for item in sorted(directory.iterdir()):
        yield item
        if item.is_dir() and item.name != ".git":
            yield from _walk(item)


def _should_skip(rel_path):
    """Check if a relative path should be skipped during copy."""
    parts = rel_path.parts
    for part in parts:
        if part in SKIP_NAMES:
            return True
    return False


def _replace_path_placeholders(rel_path, replacements):
    """Replace {{PLACEHOLDER}} patterns in path components."""
    parts = []
    for part in rel_path.parts:
        new_part = replace_placeholders(part, replacements)
        parts.append(new_part)
    return Path(*parts) if parts else rel_path


def regenerate_template_registry(target_dir):
    """Regenerate .template_registry.json with fresh SHA-256 hashes."""
    target_dir = Path(target_dir)
    spawn_dir = target_dir / ".spawn"
    if not spawn_dir.exists():
        return

    registry_file = spawn_dir / ".template_registry.json"

    files = {}
    directories = {}
    file_idx = 1
    dir_idx = 1

    for item in sorted(target_dir.rglob("*")):
        rel = item.relative_to(target_dir)

        if ".spawn" in rel.parts or "__pycache__" in rel.parts:
            continue
        # Owner's rule: a dropbox or an .archive is listed, never looked into.
        if {"dropbox", ".archive"}.intersection(rel.parts[:-1]):
            continue

        if item.is_dir():
            dir_id = f"d{dir_idx:03d}"
            directories[dir_id] = {
                "path": rel.as_posix(),
                "name": item.name,
            }
            dir_idx += 1
        elif item.is_file():
            file_id = f"f{file_idx:03d}"
            try:
                content = item.read_bytes()
                content_hash = hashlib.sha256(content).hexdigest()[:12]
            except (IOError, PermissionError) as e:
                logger.error(f"[spawn] Failed to read file for hashing {item}: {e}")
                content_hash = "unreadable"

            has_placeholder = False
            try:
                text = item.read_text(encoding="utf-8")
                has_placeholder = "{{" in text and "}}" in text
            except (UnicodeDecodeError, IOError) as e:
                logger.warning(f"[spawn] Failed to check placeholders in {item}: {e}")

            files[file_id] = {
                "path": rel.as_posix(),
                "name": item.name,
                "content_hash": content_hash,
                "has_branch_placeholder": has_placeholder,
            }
            file_idx += 1

    registry = {
        "metadata": {
            "description": "Template registry for tracking files",
            "generated": True,
        },
        "files": files,
        "directories": directories,
    }

    atomic_write_text(registry_file, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
