# =================== AIPass ====================
# Name: tab_renderer.py
# Description: Config-generated state-tabs for .trinity memory files
# Version: 1.7.0
# Created: 2026-06-25
# Modified: 2026-10-17
# =============================================

"""
Tab Renderer Handler
"""

import json
from pathlib import Path
from typing import Any, Dict

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.json import entry_limits
from aipass.memory.apps.handlers.repo_root import module_file
from aipass.memory.apps.handlers.rollover import todo_roll

logger = get_system_logger()

# Templates own every word of prose; this module owns the numbers. Never copy template text here.
_TEMPLATES_DIR = module_file(__file__).parents[3] / "templates"

_TEMPLATE_FILES = {
    "local": "LOCAL.template.json",
    "observations": "OBSERVATIONS.template.json",
}

_SECTION_TEMPLATE = {
    "todos": ("local", "todos_meta", "{{TODOS_META}}"),
    "key_learnings": ("local", "key_learnings_meta", "{{KEY_LEARNINGS_META}}"),
    "sessions": ("local", "sessions_meta", "{{SESSIONS_META}}"),
    "observations": ("observations", "observations_meta", "{{OBSERVATIONS_META}}"),
}


def _load_template(file_key: str) -> dict:
    """Read a gold-source template. Raises rather than inventing text: a fallback string would stamp unagreed prose fleet-wide."""
    name = _TEMPLATE_FILES.get(file_key)
    if name is None:
        raise ValueError(f"Unknown template key: {file_key}")
    path = _TEMPLATES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def template_usage(file_key: str) -> str:
    """Return ``document_metadata._usage`` from the gold-source template."""
    usage = _load_template(file_key).get("document_metadata", {}).get("_usage")
    if not isinstance(usage, str):
        raise ValueError(f"{_TEMPLATE_FILES[file_key]}: document_metadata._usage is missing or not a string")
    return usage


def template_semantics(section_name: str) -> str:
    """Return the one-sentence meaning that rides after a section's tab (the template line minus its placeholder)."""
    entry = _SECTION_TEMPLATE.get(section_name)
    if entry is None:
        raise ValueError(f"Unknown section: {section_name}")
    file_key, meta_key, placeholder = entry
    line = _load_template(file_key).get(meta_key)
    if not isinstance(line, str):
        raise ValueError(f"{_TEMPLATE_FILES[file_key]}: {meta_key} is missing or not a string")
    return line.replace(placeholder, "").strip()


def compose_meta(
    section_name: str,
    rollover_cfg: dict,
    entry_limits_cfg: dict,
    branch_name: str,
    todo_ctx: dict | None = None,
) -> str:
    """Render a full ``*_meta`` value: machine tab, then template semantics; joined here and nowhere else."""
    tab = render_tab(section_name, rollover_cfg, entry_limits_cfg, branch_name, todo_ctx)
    return f"{tab} {template_semantics(section_name)}"


# a guessed directory or a number that might collide with the backlog.
UNKNOWN_BRANCH_DIR = "<branch>"
UNKNOWN_NEXT = "?"


def todo_context(
    branch_dir: str | None, pad: Any, backlog: dict | None = None, todos_meta: Any = None
) -> dict[str, Any]:
    """The branch context the todos tab needs, derived now: backlog directory and next number.

    The current ``todos_meta`` ``next #N`` is a floor so the number never goes backwards;
    ``next_number`` is None when the pad is not a list or the backlog is unusable.
    """
    if not branch_dir:
        return {"branch_dir": None, "next_number": None}
    state = backlog if backlog is not None else todo_roll.read_backlog(todo_roll.backlog_path_for(branch_dir))
    if state.get("error") or not isinstance(pad, list):
        logger.info(
            f"[tab_renderer] @{branch_dir} todos tab: next number unknown ({state.get('error') or 'pad not a list'})"
        )
        return {"branch_dir": branch_dir, "next_number": None}
    number = todo_roll.next_number(
        pad,
        state.get("entries", []),
        high_water=todo_roll.high_water_of(state.get("document")),
        tab_floor=todo_roll.floor_from_tab(todos_meta),
    )
    return {"branch_dir": branch_dir, "next_number": number}


def _todos_tab(rollover_cfg: dict, branch_name: str, max_chars: Any, draft: Any, todo_ctx: dict | None) -> str:
    """The todos tab: pad size from rollover config, the backlog file, the caps, the next number."""
    context = todo_ctx if isinstance(todo_ctx, dict) else {}
    branch_dir = context.get("branch_dir") or UNKNOWN_BRANCH_DIR
    number = context.get("next_number")
    next_label = number if isinstance(number, int) and not isinstance(number, bool) else UNKNOWN_NEXT
    tail = f"task ≤{max_chars} chars · draft to {draft} · next #{next_label}"
    count = config_loader.get_todos_count(branch_name, rollover_cfg)
    if count is None:
        return f"⟦ no pad size configured — nothing rolls · {tail} ⟧"
    backlog = f"{todo_roll.BACKUP_DIR}/{todo_roll.TODO_DIR}/{branch_dir}/{todo_roll.BACKLOG_FILE}"
    return f"⟦ pad of {count} · oldest roll to {backlog} · {tail} ⟧"


_LOCAL_KEY_ORDER = [
    "document_metadata",
    "todos_meta",
    "todos",
    "key_learnings_meta",
    "key_learnings",
    "sessions_meta",
    "sessions",
]

_OBSERVATIONS_KEY_ORDER = [
    "document_metadata",
    "guidelines",
    "observations_meta",
    "observations",
]


def _reorder_keys(data: Dict[str, Any], key_order: list[str]) -> Dict[str, Any]:
    """Rebuild *data* with keys in *key_order* first, then any remaining keys."""
    ordered: Dict[str, Any] = {}
    for key in key_order:
        if key in data:
            ordered[key] = data[key]
    for key in data:
        if key not in ordered:
            ordered[key] = data[key]
    return ordered


def render_tab(
    section_name: str,
    rollover_cfg: dict,
    entry_limits_cfg: dict,
    branch_name: str,
    todo_ctx: dict | None = None,
) -> str:
    """Generate the ⟦⟧ state-tab string for a section: live numbers, no prose (see :func:`compose_meta`)."""
    # Through the SAME resolver the write gate uses, so a per_branch cap override is printed too.
    entry_types = entry_limits.resolve_entry_types(entry_limits_cfg, branch_name)
    section_limits = entry_types.get(section_name, {})
    max_chars = section_limits.get("max_chars", 300)
    field = section_limits.get("field", "value")
    draft = entry_limits.draft_target(max_chars)

    if section_name == "todos":
        return _todos_tab(rollover_cfg, branch_name, max_chars, draft, todo_ctx)

    # This banner reads as an instruction in the agent's own file: it must state what the engine
    # enforces, so ask the ONE resolver, and hand it entry_limits so the count is budget-clamped.
    count = config_loader.resolve_limits(rollover_cfg, branch_name, entry_limits_cfg).get(section_name, {}).get("count")

    if count is None:
        # No limit anywhere: naming a number would invent an instruction nothing honours.
        return f"⟦ rollover ON → no entry limit configured · {field} ≤{max_chars} chars · draft to {draft} ⟧"

    return (
        f"⟦ rollover ON → oldest archived to @memory · keep {count} · {field} ≤{max_chars} chars · draft to {draft} ⟧"
    )


def _refresh_local(branch_name, local_path, rollover_cfg, entry_limits_cfg):
    """Inject *_meta tabs into a branch's local.json. Returns (ok, error_msg)."""
    from aipass.memory.apps.handlers.json.memory_files import (
        read_memory_file_data,
        write_memory_file_simple,
    )

    data = read_memory_file_data(local_path)
    if data is None:
        return False, None  # file unreadable, skip silently

    meta = data.get("document_metadata", {})
    meta["_usage"] = template_usage("local")

    # The backlog is keyed by the branch DIRECTORY (registry casing can differ).
    local = Path(local_path)
    branch_dir = local.parent.parent.name if local.parent.name == ".trinity" else None
    pad = data.get("todos")
    todo_ctx = todo_context(branch_dir, [] if pad is None else pad, todos_meta=data.get("todos_meta"))
    for section in ("todos", "key_learnings", "sessions"):
        context = todo_ctx if section == "todos" else None
        data[f"{section}_meta"] = compose_meta(section, rollover_cfg, entry_limits_cfg, branch_name, context)
    data = _reorder_keys(data, _LOCAL_KEY_ORDER)

    if write_memory_file_simple(local_path, data):
        return True, None
    return False, f"{branch_name}/local.json: write failed"


def _refresh_observations(branch_name, obs_path, rollover_cfg, entry_limits_cfg):
    """Inject observations_meta tab into a branch's observations.json. Returns (ok, error_msg)."""
    from aipass.memory.apps.handlers.json.memory_files import (
        read_memory_file_data,
        write_memory_file_simple,
    )

    data = read_memory_file_data(obs_path)
    if data is None:
        return False, None  # file unreadable, skip silently

    meta = data.get("document_metadata", {})
    meta["_usage"] = template_usage("observations")

    data["observations_meta"] = compose_meta("observations", rollover_cfg, entry_limits_cfg, branch_name)
    data = _reorder_keys(data, _OBSERVATIONS_KEY_ORDER)

    if write_memory_file_simple(obs_path, data):
        return True, None
    return False, f"{branch_name}/observations.json: write failed"


def refresh_all_tabs(branches: list[str] | None = None) -> dict:
    """Render and write state-tabs to branch .trinity files.

    Pass a scope: unscoped (None) walks the whole registry, reserved for fleet-wide lanes like the push.
    """
    from aipass.memory.apps.handlers.json.config_loader import (
        load as load_config,
    )
    from aipass.memory.apps.handlers.monitor.detector import (
        _read_registry,
        _get_memory_file_path,
    )

    config = load_config()
    rollover_cfg = config.get("rollover", {})
    entry_limits_cfg = config.get("entry_limits", {})

    registry = _read_registry()
    if not registry:
        return {
            "success": True,
            "updated": 0,
            "skipped": 0,
            "message": "No branches in registry",
        }

    if branches is not None:
        wanted = {name.lstrip("@").lower() for name in branches}
        registry = [item for item in registry if item.get("name", "").lower() in wanted]
        if not registry:
            return {
                "success": True,
                "updated": 0,
                "skipped": 0,
                "message": f"No registry match for {', '.join(sorted(wanted))}",
            }

    updated = 0
    skipped = 0
    errors: list[str] = []

    for branch in registry:
        branch_name = branch.get("name", "UNKNOWN").lower()
        for mem_type in ("local", "observations"):
            u, s, e = _refresh_one_file(
                branch,
                branch_name,
                mem_type,
                rollover_cfg,
                entry_limits_cfg,
                _get_memory_file_path,
            )
            updated += u
            skipped += s
            errors.extend(e)

    json_handler.log_operation(
        "refresh_all_tabs",
        {"updated": updated, "skipped": skipped, "errors": len(errors), "scoped": branches is not None},
        module_name="tab_renderer",
    )
    logger.info(
        f"[tab_renderer] Refreshed tabs: {updated} updated, {skipped} skipped, {len(errors)} errors",
    )

    return {
        "success": True,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


def refresh_moved_limits(entry_type: str, before: dict, after: dict) -> dict[str, list] | None:
    """Re-render the meta lines of every registry branch whose enforced *entry_type* count moved.

    Returns None, never a dict, when the registry is unreadable.
    """
    from aipass.memory.apps.handlers.monitor.detector import RegistryUnreadable, _read_registry

    try:
        registry = _read_registry()
    except RegistryUnreadable as exc:
        logger.error(f"[tab_renderer] meta lines not re-rendered after a {entry_type} limit write: {exc}")
        return None

    moved = []
    for item in registry:
        name = str(item.get("name", "")).lower()
        old = config_loader.resolve_limits(before.get("rollover", {}), name, before.get("entry_limits"))
        new = config_loader.resolve_limits(after.get("rollover", {}), name, after.get("entry_limits"))
        if old[entry_type]["count"] != new[entry_type]["count"]:
            moved.append(name)

    errors = refresh_all_tabs(branches=moved).get("errors", []) if moved else []
    return {"branches": moved, "errors": errors}


def render_all_meta_tabs(branch_dir: str | None = None) -> dict[str, str]:
    """Render all four *_meta tab strings from memory.config.json defaults; public API for @spawn.

    Without *branch_dir* the todos tab renders ``<branch>`` and ``next #?``, never a guessed number.
    """
    from aipass.memory.apps.handlers.json.config_loader import (
        load as load_config,
    )

    config = load_config()
    rollover_cfg = config.get("rollover", {})
    entry_limits_cfg = config.get("entry_limits", {})

    _default = "__template_default__"
    return {
        "TODOS_META": render_tab("todos", rollover_cfg, entry_limits_cfg, _default, todo_context(branch_dir, [])),
        "KEY_LEARNINGS_META": render_tab("key_learnings", rollover_cfg, entry_limits_cfg, _default),
        "SESSIONS_META": render_tab("sessions", rollover_cfg, entry_limits_cfg, _default),
        "OBSERVATIONS_META": render_tab("observations", rollover_cfg, entry_limits_cfg, _default),
    }


def _refresh_one_file(branch, branch_name, mem_type, rollover_cfg, entry_limits_cfg, get_path_fn):
    """Refresh tabs for a single memory file. Returns (updated, skipped, errors)."""
    file_path = get_path_fn(branch, mem_type)
    if file_path is None:
        return 0, 1, []

    refresher = _refresh_local if mem_type == "local" else _refresh_observations
    try:
        ok, err = refresher(
            branch_name,
            file_path,
            rollover_cfg,
            entry_limits_cfg,
        )
    except Exception as e:
        logger.warning(f"[tab_renderer] {branch_name}/{mem_type}.json: {e}")
        return 0, 0, [f"{branch_name}/{mem_type}.json: {e}"]

    if ok:
        _bump_receipt(file_path)
        return 1, 0, []
    if err:
        return 0, 0, [err]
    return 0, 1, []


def _bump_receipt(file_path) -> None:
    """Record the re-render on the branch's receipt; a missing one is never created (this pass cannot know the template version)."""
    from aipass.memory.apps.handlers.templates import receipt

    trinity_dir = file_path.parent
    if trinity_dir.name != ".trinity":
        return
    result = receipt.bump_config_rendered(trinity_dir)
    if not result["success"]:
        logger.debug(f"[tab_renderer] receipt not bumped for {trinity_dir}: {result['error']}")
