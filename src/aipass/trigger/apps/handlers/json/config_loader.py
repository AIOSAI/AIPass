# =================== AIPass ====================
# Name: config_loader.py
# Description: Operator config loader for trigger.config.json
# Version: 1.0.0
# Created: 2026-08-08
# Modified: 2026-10-17
# =============================================

"""
Trigger Config Loader"""

import copy
import json
import os
from typing import Any

from aipass.trigger.apps.config import TRIGGER_JSON_DIR, TRIGGER_ROOT, replace_with_retry, trail_logger

CONFIG_PATH = TRIGGER_JSON_DIR / "custom_config" / "trigger.config.json"

# A .jsonl sidecar, not prax: this loader runs on the log watchers' event path.
logger = trail_logger(TRIGGER_ROOT / "logs" / "config_loader.jsonl")

DEFAULT_CONFIG: dict[str, Any] = {
    "_meta": {
        "escalation": {
            "consumers": [
                "handlers/escalation.py",
                "handlers/events/error_detected.py",
                "handlers/events/warning_logged.py",
                "modules/escalation.py",
            ],
            "purpose": "Repeat warning/error signatures -> one digest email to the escalation recipient",
        },
    },
    "escalation": {
        "enabled": True,
        # A manager address: email only, never a wake.
        "digest_recipient": "@devpulse",
        "warning_threshold": 10,
        "error_threshold": 5,
        "window_minutes": 60,
        "cooldown_minutes": 360,
        # A WARNING repeating this long after first seen goes to its branch, not the manager; 0 disables.
        "warning_age_hours": 24,
        "rollup_hours": 24,
        "sample_lines": 3,
        "max_signatures": 500,
        "escalate_suppressed": False,
        "watch_branch_log_warnings": True,
        # A deliberate volume mute; a medic mute does NOT belong here.
        "ignore_branches": [],
    },
}


def deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge *overrides* into *base* without mutating either."""
    result = copy.deepcopy(base)
    for key, val in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def _write_config_file(config: dict[str, Any]) -> bool:
    """Write *config* to CONFIG_PATH atomically.

    Readers are concurrent, and a half-written file would read as corrupt."""
    tmp_path = CONFIG_PATH.parent / f"{CONFIG_PATH.name}.tmp-{os.getpid()}"
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        replace_with_retry(str(tmp_path), str(CONFIG_PATH))
        return True
    except OSError as exc:
        logger.error(f"failed to write {CONFIG_PATH}: {exc}")
        return False
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning(f"could not clean up temp file {tmp_path}")


def load() -> dict[str, Any]:
    """Load trigger.config.json, deep-merged over DEFAULT_CONFIG.

    A missing file is regenerated; one that exists but will not read is never written over."""
    if not CONFIG_PATH.exists():
        written = _write_config_file(DEFAULT_CONFIG)
        logger.info(f"regenerated {CONFIG_PATH} from defaults (missing), written={written}")
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        file_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error(f"unreadable config at {CONFIG_PATH}, serving defaults in memory: {exc}")
        return copy.deepcopy(DEFAULT_CONFIG)

    if not isinstance(file_config, dict):
        logger.error(f"config at {CONFIG_PATH} is {type(file_config).__name__}, expected object")
        return copy.deepcopy(DEFAULT_CONFIG)

    return deep_merge(DEFAULT_CONFIG, file_config)


def section(name: str) -> dict[str, Any]:
    """Return a single top-level section from the config."""
    value = load().get(name, {})
    return value if isinstance(value, dict) else {}
