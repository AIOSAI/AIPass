# =================== AIPass ====================
# Name: provision.py
# Description: Caller Auto-Provisioning Handler
# Version: 1.0.1
# Created: 2025-11-16
# Modified: 2026-10-17
# =============================================

"""
Caller Auto-Provisioning Handler

Internal-only, not a CLI command: client.get_response() calls ensure_caller_config().
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from aipass.prax import logger

from aipass.api.apps.handlers.openrouter.caller import detect_caller_from_stack

from aipass.api.apps.handlers.json import json_handler


def read_json(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Read JSON file safely

    None only when absent; an unreadable file raises, else a transient read error regenerates a good config.
    """
    if not file_path.exists():
        return None

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(file_path: Path, data: Dict[str, Any]) -> bool:
    """Write JSON file safely with formatting"""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return True
    except Exception as e:
        logger.error(f"Failed to write {file_path}: {e}")
        return False


def get_default_caller_config() -> Dict[str, Any]:
    """Get default config template for new callers"""
    return {
        "module_name": "openrouter",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "ai_model": "",  # no default: the caller sets its own model
            "ai_temperature": 0.7,
            "ai_max_tokens": 4000,
            "enabled": True,
        },
    }


def get_default_caller_data() -> Dict[str, Any]:
    """Get default data template for tracking caller usage"""
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
    """Get default log template for caller operations"""
    return {"module_name": "openrouter", "timestamp": datetime.now().isoformat(), "logs": []}


def provision_json_folder(json_folder: Path) -> bool:
    """Create JSON folder structure if missing"""
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
    """Create new caller configuration with defaults"""
    try:
        if not provision_json_folder(json_folder):
            return {}

        config_file = json_folder / "openrouter_config.json"
        config = get_default_caller_config()

        if not write_json(config_file, config):
            return {}

        logger.info(f"Created API config for {caller}: {config_file}")
        logger.info(f"Created config: {config_file.name}")

        data_file = json_folder / "openrouter_data.json"
        data = get_default_caller_data()

        if write_json(data_file, data):
            logger.info(f"Created data file for {caller}: {data_file}")
            logger.info(f"Created data: {data_file.name}")

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
    """Ensure caller has API configuration, create if missing"""
    try:
        json_folder = None
        if not caller:
            detected_caller, json_folder = detect_caller_from_stack()
            if detected_caller:
                caller = detected_caller
                logger.info(f"Auto-detected caller: {caller}")
            else:
                logger.warning("Could not detect caller module")
                return {}

        if not json_folder:
            _, json_folder = detect_caller_from_stack()
            if not json_folder:
                logger.error(f"Could not find JSON folder for '{caller}'")
                return {}

        config_file = json_folder / "openrouter_config.json"

        if config_file.exists():
            try:
                config = read_json(config_file)
            except ValueError as e:
                logger.warning(f"Config file for {caller} does not parse ({e}), regenerating")
                config = None
            if config:
                logger.info(f"Using existing config for {caller}")
                return config
            else:
                logger.warning(f"Config file corrupted for {caller}, regenerating")

        return create_caller_config(caller, json_folder)

    except Exception as e:
        logger.error(f"Config provisioning failed: {e}")
        return {}
