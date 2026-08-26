# =================== AIPass ====================
# Name: tab_renderer.py
# Description: Config-generated state-tabs for .trinity memory files
# Version: 1.1.0
# Created: 2026-06-25
# Modified: 2026-06-25
# =============================================

"""
Tab Renderer Handler

Generates per-section state-tab strings (e.g. ``⟦ rollover ON ... ⟧``) from
``memory.config.json`` and writes them as ``*_meta`` keys into every branch's
``.trinity/local.json`` and ``.trinity/observations.json``.

Purpose:
    Make memory files self-documenting.  Each section carries a single-line
    banner that tells the editing agent whether rollover is ON/OFF, the keep
    count, and the char cap — all derived from config so they never drift.

Independence:
    Uses config_loader for config, detector helpers for branch discovery,
    and memory_files for safe I/O.  No service or module dependencies.
"""

import json
from pathlib import Path
from typing import Any, Dict

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader

logger = get_system_logger()

# =============================================================================
# TEMPLATE TEXT — the gold source, read never copied
# =============================================================================

# The templates own every word of prose in a memory file; this module owns the
# numbers. It used to own both: two `_CORRECTED_USAGE_*` constants held their
# own copy of the `_usage` sentence and overwrote every live file from them, so
# editing the gold source changed what new branches were born with and nothing
# else. A second copy of a text is a second source of truth, which is the exact
# disease the one-source rule exists to cure — the constants are retired and
# the text is read from the template at render time.

_TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"

_TEMPLATE_FILES = {
    "local": "LOCAL.template.json",
    "observations": "OBSERVATIONS.template.json",
}

# Which template carries the semantics sentence for each section, and under
# which key it lives there.
_SECTION_TEMPLATE = {
    "todos": ("local", "todos_meta", "{{TODOS_META}}"),
    "key_learnings": ("local", "key_learnings_meta", "{{KEY_LEARNINGS_META}}"),
    "sessions": ("local", "sessions_meta", "{{SESSIONS_META}}"),
    "observations": ("observations", "observations_meta", "{{OBSERVATIONS_META}}"),
}


def _load_template(file_key: str) -> dict:
    """Read a gold-source template. Raises rather than inventing text.

    There is deliberately no fallback string here. A fallback IS the constant
    this build retired — it would let a missing or unreadable template pass
    silently and stamp prose nobody agreed to across the fleet. Refusing to
    write is the safe failure; writing a guess is not.
    """
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
    """Return the one-sentence meaning that rides after a section's tab.

    The template stores the line as ``{{SECTION_META}} <sentence>``; the
    placeholder is the slot the rendered caps tab fills, so the sentence is
    what remains once it is removed.
    """
    entry = _SECTION_TEMPLATE.get(section_name)
    if entry is None:
        raise ValueError(f"Unknown section: {section_name}")
    file_key, meta_key, placeholder = entry
    line = _load_template(file_key).get(meta_key)
    if not isinstance(line, str):
        raise ValueError(f"{_TEMPLATE_FILES[file_key]}: {meta_key} is missing or not a string")
    return line.replace(placeholder, "").strip()


def compose_meta(section_name: str, rollover_cfg: dict, entry_limits_cfg: dict, branch_name: str) -> str:
    """Render a full ``*_meta`` value: machine tab, then template semantics.

    Numbers from config, prose from the template, joined here and nowhere
    else — so a refresh can never strip the meaning off a line it re-renders.
    """
    tab = render_tab(section_name, rollover_cfg, entry_limits_cfg, branch_name)
    return f"{tab} {template_semantics(section_name)}"


# =============================================================================
# KEY ORDERING
# =============================================================================

# Canonical key order for local.json
_LOCAL_KEY_ORDER = [
    "document_metadata",
    "todos_meta",
    "todos",
    "key_learnings_meta",
    "key_learnings",
    "sessions_meta",
    "sessions",
]

# Canonical key order for observations.json
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
    # Append any keys not in the canonical order
    for key in data:
        if key not in ordered:
            ordered[key] = data[key]
    return ordered


# =============================================================================
# TAB RENDERING
# =============================================================================


def render_tab(
    section_name: str,
    rollover_cfg: dict,
    entry_limits_cfg: dict,
    branch_name: str,
) -> str:
    """Generate the state-tab string for a section.

    Args:
        section_name: One of 'key_learnings', 'sessions', 'observations', 'todos'.
        rollover_cfg: The ``rollover`` section from memory.config.json.
        entry_limits_cfg: The ``entry_limits`` section from memory.config.json.
        branch_name: Branch name (lowercase) for per-branch overrides.

    Returns:
        The rendered tab string (e.g. ``⟦ rollover ON ... ⟧``) — the ⟦⟧ tab
        alone, carrying live numbers and no prose. Use :func:`compose_meta`
        for the full ``*_meta`` value.
    """
    # --- Resolve entry-limits for this section --------------------------------
    entry_types = entry_limits_cfg.get("entry_types", {})
    section_limits = entry_types.get(section_name, {})
    max_chars = section_limits.get("max_chars", 300)
    field = section_limits.get("field", "value")

    # --- Todos are special: rollover OFF, static shape ------------------------
    # Numbers only. The RULE sentence that used to be appended here is prose,
    # and prose is the template's — it now rides after the placeholder in
    # LOCAL.template.json where every other section's semantics live.
    if section_name == "todos":
        return f"⟦ rollover OFF — operational, never trimmed · cap ~10 entries · task ≤{max_chars} chars ⟧"

    # --- Rollover sections: ask the ONE resolver, never re-derive --------------
    # This banner is written INTO the agent's own memory file, where it reads as
    # an instruction about that agent's limits. It must therefore state what the
    # engine actually enforces. The old local lookup did neither: it fell back
    # per-branch-dict instead of per-file-key (so a per_branch entry missing its
    # `local` block silently ignored the defaults the engine would have used),
    # and it hard-defaulted a missing count to 15 — printing a limit that does
    # not exist. Both are gone: config_loader.resolve_limits is the single
    # implementation, shared with `config get` and pinned against the detector.
    count = config_loader.resolve_limits(rollover_cfg, branch_name).get(section_name, {}).get("count")

    if count is None:
        # No limit anywhere for this section — say so. Naming a number here
        # would be inventing an instruction nothing will honour.
        return f"⟦ rollover ON → no entry limit configured · {field} ≤{max_chars} chars ⟧"

    return f"⟦ rollover ON → oldest archived to @memory · keep {count} · {field} ≤{max_chars} chars ⟧"


# =============================================================================
# PER-FILE TAB WRITERS
# =============================================================================


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

    for section in ("todos", "key_learnings", "sessions"):
        data[f"{section}_meta"] = compose_meta(section, rollover_cfg, entry_limits_cfg, branch_name)
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


# =============================================================================
# REFRESH ALL BRANCHES
# =============================================================================


def refresh_all_tabs() -> dict:
    """Render and write state-tabs to all branch .trinity files.

    Walks the registry, reads each branch's memory files, computes tab
    strings from config, injects them as ``*_meta`` keys, and writes back
    with correct key ordering.

    Returns:
        Dict with success status and counts.
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

    branches = _read_registry()
    if not branches:
        return {
            "success": True,
            "updated": 0,
            "skipped": 0,
            "message": "No branches in registry",
        }

    updated = 0
    skipped = 0
    errors: list[str] = []

    for branch in branches:
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
        {"updated": updated, "skipped": skipped, "errors": len(errors)},
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


def render_all_meta_tabs() -> dict[str, str]:
    """Render all four *_meta tab strings from memory.config.json defaults.

    Public API for @spawn (and any other consumer) to resolve ``{{*_META}}``
    placeholders at branch-creation time.

    Returns:
        Dict with keys TODOS_META, KEY_LEARNINGS_META, SESSIONS_META,
        OBSERVATIONS_META — each a rendered state-tab string.
    """
    from aipass.memory.apps.handlers.json.config_loader import (
        load as load_config,
    )

    config = load_config()
    rollover_cfg = config.get("rollover", {})
    entry_limits_cfg = config.get("entry_limits", {})

    _default = "__template_default__"
    return {
        "TODOS_META": render_tab("todos", rollover_cfg, entry_limits_cfg, _default),
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
    """Record the re-render on the branch's receipt, if it has one.

    A missing receipt is not an error here and is deliberately not created:
    this pass knows the NUMBERS it just rendered, not which template version
    the files were built from. Only a push, a birth, or a reset knows that,
    and writing a guess into the receipt would defeat its one job.
    """
    from aipass.memory.apps.handlers.templates import receipt

    trinity_dir = file_path.parent
    if trinity_dir.name != ".trinity":
        return
    result = receipt.bump_config_rendered(trinity_dir)
    if not result["success"]:
        logger.debug(f"[tab_renderer] receipt not bumped for {trinity_dir}: {result['error']}")
