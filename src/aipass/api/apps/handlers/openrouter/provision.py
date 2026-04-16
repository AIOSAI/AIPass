# =================== AIPass ====================
# Name: provision.py
# Description: Caller Auto-Provisioning Handler
# Version: 1.0.0
# Created: 2025-11-16
# Modified: 2025-11-16
# =============================================

"""
Caller Auto-Provisioning Handler

Internal-only handler — not wired as a CLI command.
Called automatically by client.get_response() via ensure_caller_config().

Business logic for provisioning OpenRouter API configs:
- Auto-create caller API configurations
- Provision JSON folder structure
- Set default model/temperature/max_tokens
- Initialize caller-specific tracking files
- Ensure caller has complete 3-file JSON structure
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from aipass.prax import logger

from aipass.api.apps.handlers.openrouter.caller import detect_caller_from_stack

# JSON handler
from aipass.api.apps.handlers.json import json_handler


# ===========================================
# JSON UTILITIES
# ===========================================


def read_json(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Read JSON file safely

    Args:
        file_path: Path to JSON file

    Returns:
        Parsed JSON dict or None on error
    """
    try:
        if not file_path.exists():
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read {file_path}: {e}")
        return None


def write_json(file_path: Path, data: Dict[str, Any]) -> bool:
    """
    Write JSON file safely with formatting

    Args:
        file_path: Path to JSON file
        data: Dict to write as JSON

    Returns:
        True if successful, False otherwise
    """
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return True
    except Exception as e:
        logger.error(f"Failed to write {file_path}: {e}")
        return False


# ===========================================
# DEFAULT CONFIGURATION
# ===========================================


def get_default_caller_config() -> Dict[str, Any]:
    """
    Get default config template for new callers

    NOTE: No default ai_model - callers must set their own model in their branch config

    Returns:
        Dict with default OpenRouter configuration (model must be set by caller)
    """
    return {
        "module_name": "openrouter",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "ai_model": "",  # Caller must set their own model
            "ai_temperature": 0.7,
            "ai_max_tokens": 4000,
            "enabled": True,
        },
    }


def get_default_caller_data() -> Dict[str, Any]:
    """
    Get default data template for tracking caller usage

    Returns:
        Dict with initial usage tracking data
    """
    return {
        "module_name": "openrouter",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "models_used": {},
            "last_request": None,
        },
    }


def get_default_caller_log() -> Dict[str, Any]:
    """
    Get default log template for caller operations

    Returns:
        Dict with empty log structure
    """
    return {"module_name": "openrouter", "timestamp": datetime.now().isoformat(), "logs": []}


# ===========================================
# PROVISIONING FUNCTIONS
# ===========================================


def provision_json_folder(json_folder: Path) -> bool:
    """
    Create JSON folder structure if missing

    Args:
        json_folder: Path to caller's JSON folder

    Returns:
        True if folder exists or created, False on error
    """
    try:
        if json_folder.exists():
            return True

        json_folder.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created JSON folder: {json_folder}")

        return True
    except Exception as e:
        logger.error(f"Failed to create JSON folder: {e}")
        return False


def create_caller_config(caller: str, json_folder: Path) -> Dict[str, Any]:
    """
    Create new caller configuration with defaults

    Creates complete 3-file JSON structure:
    - openrouter_config.json (API settings)
    - openrouter_data.json (usage tracking)
    - openrouter_log.json (operation log)

    Args:
        caller: Name of calling module
        json_folder: Path to caller's JSON folder

    Returns:
        Dict with created config or empty dict on error
    """
    try:
        # Ensure JSON folder exists
        if not provision_json_folder(json_folder):
            return {}

        # Create config file
        config_file = json_folder / "openrouter_config.json"
        config = get_default_caller_config()

        if not write_json(config_file, config):
            return {}

        logger.info(f"Created API config for {caller}: {config_file}")
        logger.info(f"Created config: {config_file.name}")

        # Create data file
        data_file = json_folder / "openrouter_data.json"
        data = get_default_caller_data()

        if write_json(data_file, data):
            logger.info(f"Created data file for {caller}: {data_file}")
            logger.info(f"Created data: {data_file.name}")

        # Create log file
        log_file = json_folder / "openrouter_log.json"
        log_data = get_default_caller_log()

        if write_json(log_file, log_data):
            logger.info(f"Created log file for {caller}: {log_file}")
            logger.info(f"Created log: {log_file.name}")

        logger.info(f"Auto-provisioned OpenRouter config for '{caller}'")
        logger.warning("Reload config and retry request")
        json_handler.log_operation("provider_provisioned", {"caller": caller})

        return config

    except Exception as e:
        logger.error(f"Config creation failed: {e}")
        return {}


def ensure_caller_config(caller: str | None = None) -> Dict[str, Any]:
    """
    Ensure caller has API configuration, create if missing

    Auto-detects caller if not provided. Creates complete 3-file
    JSON structure with default OpenRouter settings.

    Args:
        caller: Optional caller name (auto-detected if None)

    Returns:
        Dict with config or empty dict if unable to provision
    """
    try:
        # Auto-detect caller if not provided
        json_folder = None
        if not caller:
            detected_caller, json_folder = detect_caller_from_stack()
            if detected_caller:
                caller = detected_caller
                logger.info(f"Auto-detected caller: {caller}")
            else:
                logger.warning("Could not detect caller module")
                return {}

        # Get JSON folder path if not already detected
        if not json_folder:
            _, json_folder = detect_caller_from_stack()
            if not json_folder:
                logger.error(f"Could not find JSON folder for '{caller}'")
                return {}

        # Check if config already exists
        config_file = json_folder / "openrouter_config.json"

        if config_file.exists():
            config = read_json(config_file)
            if config:
                logger.info(f"Using existing config for {caller}")
                return config
            else:
                logger.warning(f"Config file corrupted for {caller}, regenerating")

        # Create new config
        return create_caller_config(caller, json_folder)

    except Exception as e:
        logger.error(f"Config provisioning failed: {e}")
        return {}
