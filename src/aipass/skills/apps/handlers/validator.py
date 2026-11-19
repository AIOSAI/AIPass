# =================== AIPass ====================
# Name: validator.py
# Description: Check skill requirements
# Version: 1.1.1
# Created: 2026-03-07
# Modified: 2026-11-17
# =============================================

"""Skill requirement checking: can this skill actually run here?"""

import importlib.util
import os
import shutil

from aipass.prax import logger
from aipass.skills.apps.handlers.json import json_handler


def validate_skill(skill_metadata):
    """Check if a skill's requires block is met; a malformed block is never read as met."""
    # PyYAML loads `requires:` with nothing under it as None: no requirements.
    requires = skill_metadata.get("requires") or {}
    if not isinstance(requires, dict):
        logger.warning(f"requires is a {type(requires).__name__}, not a pip/bins/config mapping")
        return {
            "valid": False,
            "missing_pip": [],
            "missing_bins": [],
            "missing_config": [],
            "malformed": f"requires must map pip/bins/config to lists, not a {type(requires).__name__}",
        }

    pip_packages = requires.get("pip", []) or []
    bins = requires.get("bins", []) or []
    config_keys = requires.get("config", []) or []

    missing_pip = _check_pip(pip_packages)
    missing_bins = _check_bins(bins)
    missing_config = _check_config(config_keys)

    valid = not (missing_pip or missing_bins or missing_config)

    json_handler.log_operation(
        "validation_check",
        {
            "valid": valid,
            "missing_count": len(missing_pip) + len(missing_bins) + len(missing_config),
        },
    )

    return {
        "valid": valid,
        "missing_pip": missing_pip,
        "missing_bins": missing_bins,
        "missing_config": missing_config,
    }


def _check_pip(packages):
    """Check which pip packages are missing."""
    missing = []
    for pkg in packages:
        # Top-level name only: find_spec raises for a dotted name whose parent package is absent.
        import_name = pkg.replace("-", "_").split(".")[0]
        if importlib.util.find_spec(import_name) is None:
            missing.append(pkg)
    return missing


def _check_bins(bins):
    """Check which CLI binaries are missing from PATH."""
    missing = []
    for binary in bins:
        if shutil.which(binary) is None:
            missing.append(binary)
    return missing


def _check_config(config_keys):
    """Check which config/env vars are missing."""
    missing = []
    for key in config_keys:
        if os.environ.get(key) is None:
            missing.append(key)
    return missing
