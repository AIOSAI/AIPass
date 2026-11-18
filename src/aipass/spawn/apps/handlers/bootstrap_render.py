# =================== AIPass ====================
# Name: bootstrap_render.py
# Description: The install script's .trinity render for a core branch: seed first, then the template
# Version: 1.1.2
# Created: 2026-11-17
# Modified: 2026-11-18
# =============================================

"""Render a core branch's missing .trinity files at install time, before drone exists.

Served on spawn's package door so setup.sh calls one name instead of three handler paths."""

import json
import uuid
from pathlib import Path

from aipass.memory import render_all_meta_tabs
from aipass.prax import logger
from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.class_registry import get_template_dir, resolve_template_class
from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.metadata import normalize_branch_name
from aipass.spawn.apps.handlers.placeholders import build_replacements_dict, replace_placeholders
from aipass.spawn.apps.handlers.registry import branches_as_list, entry_path
from aipass.spawn.apps.handlers.seed_ops import find_seed, load_seed, mint_and_write, seed_path_for

TRINITY_FILES = ("passport.json", "local.json", "observations.json")


def render_bootstrap_trinity(
    branch_name: str, target: Path, citizen_class: str, role: str, registry_path: Path
) -> list[str]:
    """Write the .trinity files ``target`` lacks; return the names written. An existing file is never touched.

    A tracked passport seed births the passport first, with fresh machine-local ids. A seed that fails
    validation, or a registry that is missing or unreadable, raises: the install stops loudly.
    """
    target = Path(target)
    written = []
    passport_dest = target / ".trinity" / "passport.json"
    seed_file = find_seed(target)
    if seed_file is not None and not passport_dest.exists():
        try:
            registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("[spawn] bootstrap of %s cannot read registry %s: %s", branch_name, registry_path, exc)
            raise
        mint_and_write(
            seed_file,
            passport_dest,
            branch_name=branch_name,
            registry_id=registry.get("metadata", {}).get("id", ""),
            citizen_id=str(uuid.uuid4()),
        )
        written.append("passport.json(seed)")

    template_dir = get_template_dir(resolve_template_class({"citizen_class": citizen_class, "role": role}))
    replacements = build_replacements_dict(
        target,
        branch_name,
        role=role,
        purpose=role,
        citizen_class=citizen_class,
        meta_tabs=render_all_meta_tabs(),
    )
    # The default MODULE is bare, for project branches; every core branch imports as aipass.<name>.
    if replacements["RESIDENCY"] == "core":
        replacements["MODULE"] = f"aipass.{replacements['branchname']}"

    for filename in TRINITY_FILES:
        dest = target / ".trinity" / filename
        if dest.exists():
            continue
        source = (template_dir / ".trinity" / filename).read_text(encoding="utf-8")
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(dest, replace_placeholders(source, replacements))
        written.append(filename)

    json_handler.log_operation("bootstrap_rendered", data={"branch": branch_name, "written": written})
    return written


def restore_citizen(branch_name: str, registry_path: Path) -> list[str]:
    """Restore one registered citizen's missing .trinity files: the installer's render, fed by its row and seed.

    The folder comes from the registry row; class, role and name come from the citizen's own seed, so
    no list of classes or roles lives here. Unregistered, folderless or seedless raises, nothing written.
    """
    registry_path = Path(registry_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    wanted = normalize_branch_name(branch_name, "lower")
    rows = [
        row
        for row in branches_as_list(registry.get("branches", []))
        if normalize_branch_name(row.get("name", ""), "lower") == wanted
    ]
    if not rows:
        logger.error("[spawn] restore: %s is not registered in %s", branch_name, registry_path)
        raise LookupError(f"{branch_name} is not registered in {registry_path}")
    target = registry_path.parent / entry_path(rows[0])
    seed_file = find_seed(target)
    if seed_file is None:
        reason = (
            f"{branch_name} carries no seed at {seed_path_for(target)} - while a passport still exists, "
            f"run `drone @spawn export-seeds --confirm` in {registry_path.parent} to write one"
        )
        logger.error("[spawn] restore: %s", reason)
        raise FileNotFoundError(reason)
    seed = load_seed(seed_file)
    identity = seed.get("identity", {})
    return render_bootstrap_trinity(
        seed["branch_info"]["branch_name"],
        target,
        identity.get("citizen_class", ""),
        identity.get("role", ""),
        registry_path,
    )
