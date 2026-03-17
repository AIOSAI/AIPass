# =================== AIPass ====================
# Name: validator.py
# Description: Check skill requirements
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

import importlib.util
import os
import shutil

from skills.apps.handlers.json import json_handler


def validate_skill(skill_metadata):
    """Check if a skill's requirements are met.

    Args:
        skill_metadata: Dict with 'requires' key containing:
            - pip: list of Python package names
            - bins: list of CLI tool names
            - config: list of env var / config key names

    Returns:
        dict: {
            "valid": bool,
            "missing_pip": list[str],
            "missing_bins": list[str],
            "missing_config": list[str]
        }
    """
    requires = skill_metadata.get("requires", {})

    pip_packages = requires.get("pip", []) or []
    bins = requires.get("bins", []) or []
    config_keys = requires.get("config", []) or []

    missing_pip = _check_pip(pip_packages)
    missing_bins = _check_bins(bins)
    missing_config = _check_config(config_keys)

    valid = not (missing_pip or missing_bins or missing_config)

    json_handler.log_operation("validation_check", {
        "valid": valid,
        "missing_count": len(missing_pip) + len(missing_bins) + len(missing_config),
    })

    return {
        "valid": valid,
        "missing_pip": missing_pip,
        "missing_bins": missing_bins,
        "missing_config": missing_config,
    }


def _check_pip(packages):
    """Check which pip packages are missing.

    Args:
        packages: List of Python package names.

    Returns:
        list[str]: Names of packages that are not installed.
    """
    missing = []
    for pkg in packages:
        # Normalize package name for import (e.g., some-pkg -> some_pkg)
        import_name = pkg.replace("-", "_")
        try:
            spec = importlib.util.find_spec(import_name)
            if spec is None:
                missing.append(pkg)
        except (ModuleNotFoundError, ValueError):
            missing.append(pkg)
    return missing


def _check_bins(bins):
    """Check which CLI binaries are missing from PATH.

    Args:
        bins: List of CLI tool names.

    Returns:
        list[str]: Names of binaries not found in PATH.
    """
    missing = []
    for binary in bins:
        if shutil.which(binary) is None:
            missing.append(binary)
    return missing


def _check_config(config_keys):
    """Check which config/env vars are missing.

    Args:
        config_keys: List of environment variable names.

    Returns:
        list[str]: Names of env vars that are not set.
    """
    missing = []
    for key in config_keys:
        if os.environ.get(key) is None:
            missing.append(key)
    return missing
