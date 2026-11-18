# =================== AIPass ====================
# Name: bootstrap_render.py
# Description: The install script's .trinity render for a core branch: seed first, then the template
# Version: 1.0.0
# Created: 2026-11-17
# Modified: 2026-11-17
# =============================================

"""Render a core branch's missing .trinity files at install time, before drone exists.

Served on spawn's package door so setup.sh calls one name instead of three handler paths."""

import json
import uuid
from pathlib import Path

from aipass.memory import render_all_meta_tabs
from aipass.prax import logger
from aipass.spawn.apps.handlers.class_registry import get_template_dir, resolve_template_class
from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.placeholders import build_replacements_dict, replace_placeholders
from aipass.spawn.apps.handlers.seed_ops import find_seed, mint_and_write

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
    replacements["MODULE"] = f"aipass.{replacements['branchname']}"

    for filename in TRINITY_FILES:
        dest = target / ".trinity" / filename
        if dest.exists():
            continue
        source = (template_dir / ".trinity" / filename).read_text(encoding="utf-8")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(replace_placeholders(source, replacements), encoding="utf-8")
        written.append(filename)

    json_handler.log_operation("bootstrap_rendered", data={"branch": branch_name, "written": written})
    return written
