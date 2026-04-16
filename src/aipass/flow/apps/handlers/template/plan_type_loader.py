# =================== AIPass ====================
# Name: plan_type_loader.py
# Description: Plan type plugin discovery and loading
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""
Plan Type Loader

Discovers plan type plugins from the templates/ directory using
filesystem-driven auto-discovery.  Each plan type is a subdirectory
containing one or more Markdown template files.  No per-type JSON
config is required -- the only manual configuration is the PREFIX_MAP
dict defined in this module.

Usage:
    from aipass.flow.apps.handlers.template.plan_type_loader import (
        discover_plan_types,
        get_plan_type,
    )

    # Discover all installed plan types
    types = discover_plan_types()

    # Get a specific plan type by prefix, directory name, or shorthand
    config = get_plan_type("FPLAN")
    config = get_plan_type("flow_plans")
    config = get_plan_type("master")  # resolves to flow_plans with template override
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from aipass.flow.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "plan_type_loader"

# Resolve flow root: this file lives at flow/apps/handlers/template/
# so parents[3] walks up to flow/
FLOW_ROOT = Path(__file__).resolve().parents[3]
PLAN_TYPES_DIR = FLOW_ROOT / "templates"

# Prefix map loaded from persistent registry (template_registry.json)
# Fallback to defaults if registry unavailable
_FALLBACK_PREFIX_MAP: Dict[str, str] = {
    "flow_plans": "FPLAN",
    "dev_plans": "DPLAN",
}


def _get_prefix_map() -> Dict[str, str]:
    """Load prefix map from persistent template registry."""
    try:
        from aipass.flow.apps.handlers.template.registry_ops import get_prefix_map

        return get_prefix_map()
    except Exception as exc:
        logger.warning(
            "%s: failed to load template registry, using fallback -- %s",
            MODULE_NAME,
            exc,
        )
        return _FALLBACK_PREFIX_MAP


# Standardised defaults applied to every discovered plan type
STANDARD_DIGITS = 4
STANDARD_SLUG_MAX = 45
DEFAULT_TEMPLATE_NAME = "default"

# Cache for discovered plan types -- populated on first call
_plan_type_cache: Dict[str, Dict] | None = None

# =============================================
# INTERNAL HELPERS
# =============================================


def _build_cache() -> Dict[str, Dict]:
    """Scan ``templates/`` for subdirectories and build config dicts.

    Each subdirectory that contains at least one ``.md`` file and has a
    corresponding entry in :data:`PREFIX_MAP` becomes a plan type.
    No JSON config files are read -- all metadata is derived from the
    filesystem layout and the constants defined in this module.
    """
    cache: Dict[str, Dict] = {}

    if not PLAN_TYPES_DIR.is_dir():
        logger.warning(
            "%s: templates directory not found at %s",
            MODULE_NAME,
            PLAN_TYPES_DIR,
        )
        return cache

    for child in sorted(PLAN_TYPES_DIR.iterdir()):
        if not child.is_dir():
            continue
        # Skip __pycache__ and hidden directories
        if child.name.startswith(("_", ".")):
            continue

        # Must contain at least one .md template file
        md_files = sorted(child.glob("*.md"))
        if not md_files:
            continue

        # Look up prefix from registry -- skip unknown directories
        dir_name = child.name
        prefix_map = _get_prefix_map()
        prefix = prefix_map.get(dir_name)
        if prefix is None:
            logger.warning(
                "%s: Unknown plan type '%s' in templates/. Register with: drone @flow register %s <PREFIX>",
                MODULE_NAME,
                dir_name,
                dir_name,
            )
            continue

        available_templates = [p.stem for p in md_files]

        config: Dict = {
            "name": dir_name,
            "prefix": prefix,
            "digits": STANDARD_DIGITS,
            "registry_file": f"{prefix.lower()}_registry.json",
            "available_templates": available_templates,
            "default_template": DEFAULT_TEMPLATE_NAME,
            "slug_max_length": STANDARD_SLUG_MAX,
            "_directory": child,
        }

        cache[dir_name] = config
        logger.info(
            "%s: discovered plan type '%s' (prefix=%s, templates=%s)",
            MODULE_NAME,
            dir_name,
            prefix,
            available_templates,
        )

    return cache


def _get_cache() -> Dict[str, Dict]:
    """Return the cached plan-type registry, building it on first access."""
    global _plan_type_cache  # noqa: PLW0603
    if _plan_type_cache is None:
        _plan_type_cache = _build_cache()
    return _plan_type_cache


def _resolve_type_key(type_key: str) -> tuple[str, str | None]:
    """Normalise *type_key* to a cache key and optional template override.

    Accepted forms (checked in order):

    1. Direct directory name: ``"flow_plans"``, ``"dev_plans"``
    2. Prefix (case-insensitive): ``"FPLAN"``, ``"dplan"``
    3. Template shorthand: if *type_key* matches any ``.md`` file stem in
       any plan type, resolve to that type with a template override.
       E.g. ``"master"`` resolves to ``flow_plans`` with template ``"master"``.
    4. Case-insensitive directory name fallback.

    Returns ``(cache_key, template_override_or_None)``.
    Raises ``ValueError`` when the key cannot be resolved.
    """
    cache = _get_cache()

    # 1. Direct match on cache key (directory / name)
    if type_key in cache:
        return type_key, None

    upper = type_key.upper()

    # 2. Match by prefix (case-insensitive)
    for key, cfg in cache.items():
        if cfg.get("prefix", "").upper() == upper:
            return key, None

    # 3. Dynamic template shorthand -- resolve if type_key matches any
    #    .md file stem that is NOT the default template name
    lower = type_key.lower()
    for key, cfg in cache.items():
        templates = cfg.get("available_templates", [])
        if lower in templates and lower != DEFAULT_TEMPLATE_NAME:
            return key, lower

    # 4. Case-insensitive match on name / directory
    for key, cfg in cache.items():
        if key.lower() == lower:
            return key, None

    raise ValueError(f"Unknown plan type '{type_key}'. Available: {', '.join(cache.keys())}")


# =============================================
# PUBLIC API
# =============================================


def discover_plan_types() -> Dict[str, Dict]:
    """Scan ``templates/`` and return ``{type_key: config}``.

    The *type_key* is derived from the subdirectory name.  Plan types
    are auto-discovered from the filesystem -- each subdirectory that
    contains ``.md`` files and has an entry in :data:`PREFIX_MAP` becomes
    a plan type.  Configs are also reachable by prefix -- use
    :func:`get_plan_type` for that.
    """
    # Force a fresh scan (useful after adding new plan types at runtime)
    global _plan_type_cache  # noqa: PLW0603
    _plan_type_cache = None
    cache = _get_cache()

    json_handler.log_operation(
        "plan_types_discovered",
        {
            "types_found": len(cache),
            "type_keys": list(cache.keys()),
            "success": True,
        },
    )

    return cache


def get_plan_type(type_key: str) -> Dict:
    """Return the config dict for a single plan type.

    *type_key* is flexible:

    - Directory name: ``"flow_plans"``, ``"dev_plans"``
    - Prefix (case-insensitive): ``"FPLAN"``, ``"DPLAN"``
    - Shorthand: ``"fplan"``, ``"dplan"``, ``"master"``

    When ``"master"`` is used the returned config is a **copy** of the
    ``flow_plans`` config with ``default_template`` set to ``"master"``.

    Raises:
        ValueError: If the type_key cannot be resolved.
    """
    cache_key, template_override = _resolve_type_key(type_key)
    config = _get_cache()[cache_key]

    if template_override is not None:
        # Return a shallow copy so we don't mutate the cached original
        config = {**config, "default_template": template_override}

    return config
