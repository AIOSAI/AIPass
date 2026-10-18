# =================== AIPass ====================
# Name: plan_type_loader.py
# Description: Plan type plugin discovery and loading
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-10-17
# =============================================

"""Plan Type Loader"""

from __future__ import annotations

from typing import Dict

from aipass.flow.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger


MODULE_NAME = "plan_type_loader"

from aipass.flow.apps.handlers.repo_root import module_file

FLOW_ROOT = module_file(__file__).parents[3]
PLAN_TYPES_DIR = FLOW_ROOT / "templates"

# Used only when template_registry.json cannot be read.
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


STANDARD_DIGITS = 4
STANDARD_SLUG_MAX = 45
DEFAULT_TEMPLATE_NAME = "default"

_plan_type_cache: Dict[str, Dict] | None = None


def _build_cache() -> Dict[str, Dict]:
    """Scan ``templates/`` for subdirectories and build config dicts.
    A subdirectory with no ``.md`` file or no registered prefix is not a plan type.
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
        if child.name.startswith(("_", ".")):
            continue

        md_files = sorted(child.glob("*.md"))
        if not md_files:
            continue

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
    global _plan_type_cache
    if _plan_type_cache is None:
        _plan_type_cache = _build_cache()
    return _plan_type_cache


def _resolve_type_key(type_key: str) -> tuple[str, str | None]:
    """Normalise *type_key* to a cache key and optional template override.
    Order: directory name, prefix, non-default template stem (``"master"``), case-insensitive name.
    Raises ``ValueError`` when the key cannot be resolved.
    """
    cache = _get_cache()

    if type_key in cache:
        return type_key, None

    upper = type_key.upper()

    for key, cfg in cache.items():
        if cfg.get("prefix", "").upper() == upper:
            return key, None

    lower = type_key.lower()
    for key, cfg in cache.items():
        templates = cfg.get("available_templates", [])
        if lower in templates and lower != DEFAULT_TEMPLATE_NAME:
            return key, lower

    for key, cfg in cache.items():
        if key.lower() == lower:
            return key, None

    raise ValueError(f"Unknown plan type '{type_key}'. Available: {', '.join(cache.keys())}")


def discover_plan_types() -> Dict[str, Dict]:
    """Scan ``templates/`` and return ``{type_key: config}``.
    Always rescans, so plan types added at runtime are seen.
    """
    global _plan_type_cache
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
    A template shorthand returns a copy with ``default_template`` overridden; the cache is never mutated.
    Raises ValueError if the type_key cannot be resolved.
    """
    cache_key, template_override = _resolve_type_key(type_key)
    config = _get_cache()[cache_key]

    if template_override is not None:
        config = {**config, "default_template": template_override}

    return config
