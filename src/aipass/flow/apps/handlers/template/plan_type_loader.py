# =================== AIPass ====================
# Name: plan_type_loader.py
# Description: Plan type plugin discovery and loading
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""
Plan Type Loader

Discovers and loads plan type plugins from the plan_types/ directory.
Each plan type is a subdirectory containing a plan_type.json config
and a templates/ directory with Markdown templates.

Plan types are DATA, not code -- the loader reads JSON configs and
resolves template paths without requiring any per-type Python modules.

Usage:
    from aipass.flow.apps.handlers.template.plan_type_loader import (
        discover_plan_types,
        get_plan_type,
        get_template_path,
        list_available_types,
    )

    # Discover all installed plan types
    types = discover_plan_types()

    # Get a specific plan type by prefix, directory name, or shorthand
    config = get_plan_type("FPLAN")
    config = get_plan_type("flow_plans")
    config = get_plan_type("master")  # resolves to flow_plans with template override

    # Get the path to a template file
    path = get_template_path("FPLAN")              # default template
    path = get_template_path("FPLAN", "master")    # specific template

    # List all available types for --help / introspection
    all_types = list_available_types()
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from aipass.prax.apps.modules.logger import system_logger as logger

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "plan_type_loader"

# Resolve flow root: this file lives at flow/apps/handlers/template/
# so parents[3] walks up to flow/
FLOW_ROOT = Path(__file__).resolve().parents[3]
PLAN_TYPES_DIR = FLOW_ROOT / "plan_types"

_CONFIG_FILENAME = "plan_type.json"
_TEMPLATES_SUBDIR = "templates"

# Cache for discovered plan types -- populated on first call
_plan_type_cache: Dict[str, Dict] | None = None

# =============================================
# INTERNAL HELPERS
# =============================================


def _load_plan_type_config(directory: Path) -> Dict:
    """Load and validate a single plan_type.json from *directory*.

    Returns the parsed config dict with an injected ``_directory`` key
    pointing to the plugin folder, or an empty dict if the config is
    missing or invalid.
    """
    config_path = directory / _CONFIG_FILENAME
    if not config_path.is_file():
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            config: Dict = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "%s: failed to load %s -- %s",
            MODULE_NAME,
            config_path,
            exc,
        )
        return {}

    # Inject the resolved directory so callers can find templates
    config["_directory"] = directory
    return config


def _build_cache() -> Dict[str, Dict]:
    """Scan ``plan_types/`` and return ``{type_key: config}``."""
    cache: Dict[str, Dict] = {}

    if not PLAN_TYPES_DIR.is_dir():
        logger.warning(
            "%s: plan_types directory not found at %s",
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

        config = _load_plan_type_config(child)
        if not config:
            continue

        # Key by the ``name`` field from the JSON, falling back to dir name
        type_key = config.get("name", child.name)
        cache[type_key] = config
        logger.info(
            "%s: discovered plan type '%s' (prefix=%s)",
            MODULE_NAME,
            type_key,
            config.get("prefix", "?"),
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

    Accepted forms:
    - Directory name: ``"flow_plans"``, ``"dev_plans"``
    - Prefix (any case): ``"FPLAN"``, ``"dplan"``
    - Shorthand ``"master"`` -> ``flow_plans`` with template override ``"master"``

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

    # 3. Shorthand "master" -> flow_plans with template override
    if type_key.lower() == "master":
        for key, cfg in cache.items():
            if "master" in cfg.get("available_templates", []):
                return key, "master"

    # 4. Case-insensitive match on name / directory
    lower = type_key.lower()
    for key, cfg in cache.items():
        if key.lower() == lower:
            return key, None

    raise ValueError(
        f"Unknown plan type '{type_key}'. "
        f"Available: {', '.join(cache.keys())}"
    )


# =============================================
# PUBLIC API
# =============================================


def discover_plan_types() -> Dict[str, Dict]:
    """Scan ``plan_types/`` and return ``{type_key: config}``.

    The *type_key* is derived from the ``name`` field inside each
    ``plan_type.json`` (falling back to the directory name).  Configs
    are also reachable by prefix -- use :func:`get_plan_type` for that.
    """
    # Force a fresh scan (useful after adding new plan types at runtime)
    global _plan_type_cache  # noqa: PLW0603
    _plan_type_cache = None
    return _get_cache()


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


def get_template_path(
    type_key: str,
    template_name: str | None = None,
) -> Path:
    """Return the resolved :class:`Path` to a template file.

    Parameters:
        type_key: Anything accepted by :func:`get_plan_type`.
        template_name: Template name (without ``.md``).  Defaults to the
            ``default_template`` value from the plan-type config.

    Raises:
        ValueError: If the plan type cannot be resolved.
        FileNotFoundError: If the resolved template file does not exist.
    """
    config = get_plan_type(type_key)
    template = template_name or config.get("default_template", "default")
    templates_dir: Path = config["_directory"] / _TEMPLATES_SUBDIR
    template_path = templates_dir / f"{template}.md"

    if not template_path.is_file():
        available = [
            p.stem
            for p in templates_dir.iterdir()
            if p.suffix == ".md"
        ] if templates_dir.is_dir() else []
        raise FileNotFoundError(
            f"Template '{template}' not found for plan type "
            f"'{config.get('name', type_key)}'. "
            f"Looked at: {template_path}. "
            f"Available templates: {available}"
        )

    return template_path


def list_available_types() -> List[Dict]:
    """Return a list of all discovered plan-type configs.

    Each entry is a dict copied from the JSON config with an extra
    ``_directory`` key.  Useful for ``--help`` output and introspection.
    """
    cache = _get_cache()
    return list(cache.values())
