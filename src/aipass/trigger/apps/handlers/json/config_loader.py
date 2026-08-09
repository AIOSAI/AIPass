# =================== AIPass ====================
# Name: config_loader.py
# Description: Operator config loader for trigger.config.json
# Version: 1.0.0
# Created: 2026-08-08
# Modified: 2026-08-08
# =============================================

"""
Trigger Config Loader

Single entry point for reading trigger's operator-editable settings from
trigger_json/custom_config/trigger.config.json.

Doctrine (Patrick, S193): configs live inside JSONs, not inside code. The
file on disk is the RUNTIME AUTHORITY the operator edits. DEFAULT_CONFIG
exists so that file can be REGENERATED when it goes missing — it is the
regeneration seed, not a rival source of truth. What ships as default here
is what an operator finds in the file after a regen, so the two must stay
in lockstep.

A file that exists but will not parse is NEVER written over (DPLAN-0206):
it may be one stray comma away from correct and carry hand-tuned values.
Log an ERROR, serve defaults in memory, leave the operator's file alone.

Usage:
    from aipass.trigger.apps.handlers.json.config_loader import section

    cfg = section("escalation")
"""

import copy
import json
import os
from typing import Any

from aipass.trigger.apps.config import TRIGGER_JSON_DIR, TRIGGER_ROOT, trail_logger

CONFIG_PATH = TRIGGER_JSON_DIR / "custom_config" / "trigger.config.json"

# Recursion-safe: this loader is read from the event path the log watchers
# read, so it logs to a .jsonl sidecar rather than through prax.
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
        # Master switch. False = the lane records nothing and sends nothing.
        "enabled": True,
        # Where digests land. A manager address: email only, never a wake.
        "digest_recipient": "@devpulse",
        # Occurrences of one signature inside the window before a digest fires.
        "warning_threshold": 10,
        "error_threshold": 5,
        # Rolling window, minutes. Occurrences older than this stop counting.
        "window_minutes": 60,
        # Per-signature silence after a digest fires, minutes.
        "cooldown_minutes": 360,
        # Sample log lines carried in the digest body.
        "sample_lines": 3,
        # Cap on tracked signatures — least-recently-seen are pruned first.
        "max_signatures": 500,
        # Errors an operator deliberately silenced (compass #219) stay silent
        # here too. Flip to true to escalate them anyway.
        "escalate_suppressed": False,
        # Parse WARNING lines out of branch logs. Without this, tier 1 only
        # sees system_logs/ — branch warnings have no escalation path at all.
        "watch_branch_log_warnings": True,
        # Branches whose repeats are never escalated (deliberate, like a
        # volume mute — a medic mute does NOT belong here).
        "ignore_branches": [],
    },
}


def deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge *overrides* into *base* without mutating either.

    Args:
        base: Baseline dict (defaults)
        overrides: Dict whose keys win

    Returns:
        A new merged dict
    """
    result = copy.deepcopy(base)
    for key, val in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def _write_config_file(config: dict[str, Any]) -> bool:
    """Write *config* to CONFIG_PATH atomically.

    Atomic because the watcher service, CLI and event handlers all read this
    file concurrently — a half-written file reads as corrupt, which would turn
    a routine regeneration into a fleet-wide fall back to defaults.

    Args:
        config: Config dict to write

    Returns:
        True if the file was written, False if the write failed (logged)
    """
    tmp_path = CONFIG_PATH.parent / f"{CONFIG_PATH.name}.tmp-{os.getpid()}"
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, CONFIG_PATH)
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

    A genuinely MISSING file is regenerated in full from DEFAULT_CONFIG, so
    the operator always has a real file to edit — that is the whole reason
    code carries defaults. A file that EXISTS but cannot be read is never
    written over: defaults are served in memory only.

    Returns:
        The effective config dict (always safe to use)
    """
    if not CONFIG_PATH.exists():
        written = _write_config_file(DEFAULT_CONFIG)
        logger.info(f"regenerated {CONFIG_PATH} from defaults (missing), written={written}")
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        file_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # Fail loud, do NOT overwrite — the operator must fix their file.
        logger.error(f"unreadable config at {CONFIG_PATH}, serving defaults in memory: {exc}")
        return copy.deepcopy(DEFAULT_CONFIG)

    if not isinstance(file_config, dict):
        # Valid JSON, wrong shape (a list, a bare string). deep_merge would
        # raise on it, so it takes the same no-clobber path as malformed.
        logger.error(f"config at {CONFIG_PATH} is {type(file_config).__name__}, expected object")
        return copy.deepcopy(DEFAULT_CONFIG)

    return deep_merge(DEFAULT_CONFIG, file_config)


def section(name: str) -> dict[str, Any]:
    """Return a single top-level section from the config.

    Args:
        name: Top-level section key (e.g. 'escalation')

    Returns:
        The section dict, or an empty dict when absent
    """
    value = load().get(name, {})
    return value if isinstance(value, dict) else {}
