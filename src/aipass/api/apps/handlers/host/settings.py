# =================== AIPass ====================
# Name: settings.py
# Description: Host API Settings Handler — the desktop's two gears, served
# Version: 1.0.0
# Created: 2026-08-16
# Modified: 2026-10-17
# =============================================

"""
Host API Settings Handler

A mirror of @baud's settings.rs: both faces must write these files the same way.
A file that exists but is not a JSON object refuses reads AND writes.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict

from aipass.prax import logger

# Imported, not mirrored: the flag's location is declared once, in @hooks' tree.
from aipass.hooks.apps import sound as hooks_sound
from aipass.api.apps.handlers.json import json_handler

AGENT_SETTINGS_RELATIVE = Path(".claude") / "settings.local.json"
BAUD_SETTINGS_RELATIVE = Path(".aipass") / "baud.settings.json"

HOOKS_SOUND_DOOR = ["drone", "@hooks", "hooksound"]
HOOKS_SOUND_ON = "on"
HOOKS_SOUND_OFF = "off"
HOOKS_SOUND_TIMEOUT_SECONDS = 30

KEY_MODEL = "model"
KEY_AUTO_COMPACT_ENABLED = "autoCompactEnabled"
KEY_AUTO_COMPACT_WINDOW = "autoCompactWindow"

# The allowlist IS the surgical guarantee: every other key in the file survives.
_AGENT_FIELDS: Dict[str, tuple] = {
    "model": (KEY_MODEL, str),
    "auto_compact_enabled": (KEY_AUTO_COMPACT_ENABLED, bool),
    "auto_compact_window": (KEY_AUTO_COMPACT_WINDOW, int),
}


class SettingsRefused(Exception):
    """The caller's request cannot be honoured as asked — their 400."""


class SettingsUnavailable(Exception):
    """This host could not serve the settings — our 503."""


def read_object(path: Path) -> Dict[str, Any]:
    """
    A settings file as a dict. Missing or empty reads as {} — a fresh branch
    has no settings and that is not a fault.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # The only OSError that reads as blank. NotADirectoryError must not join
        # it: a file where a directory belongs is a broken tree (rust refuses too).
        logger.debug("[host_api] no settings file at %s yet — reading as blank", path)
        return {}
    except OSError as e:
        # Answering {} here would let a patch overwrite settings that were merely unreadable.
        logger.error("[host_api] could not read settings at %s: %s", path, e)
        raise SettingsUnavailable(f"Could not read '{path.name}': {e}") from e
    if not raw.strip():
        return {}
    try:
        document = json.loads(raw)
    except ValueError as e:
        raise SettingsRefused(f"'{path}' is not valid JSON ({e}) — refusing to touch it") from e
    if not isinstance(document, dict):
        raise SettingsRefused(f"'{path}' is not a JSON object — refusing to touch it")
    return document


def _discard(staged: str) -> None:
    """Remove a staged file that never made it into place."""
    try:
        os.unlink(staged)
    except OSError as e:
        # Logged, not raised: raising would bury the write's own failure, already travelling.
        logger.warning("[host_api] staged settings file %s could not be removed: %s", staged, e)


def _replace_through_a_staged_file(directory: Path, path: Path, document: Dict[str, Any]) -> None:
    """Write the document beside its destination, then rename it over."""
    descriptor, staged = tempfile.mkstemp(dir=str(directory), prefix=".baud-settings-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(staged, path)
    # BaseException: an interrupt mid-write leaves the same orphan.
    except BaseException:
        _discard(staged)
        raise


def write_atomically(path: Path, document: Dict[str, Any]) -> None:
    """
    Replace a settings file in one step: temp file in the SAME directory (so
    the rename stays on one filesystem and is atomic), then rename over.
    """
    directory = path.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _replace_through_a_staged_file(directory, path, document)
    except OSError as e:
        logger.error("[host_api] could not write settings at %s: %s", path, e)
        raise SettingsUnavailable(f"Could not write '{path.name}': {e}") from e


def _reads_as_a_token_count(value: Any) -> bool:
    """Whether a stored value can be shown on the window dial."""
    # Unsigned like the desktop's as_u64; zero reads (only the write refuses it).
    # bool is excluded because a Python bool is also an int.
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def agent_settings_view(document: Dict[str, Any]) -> Dict[str, Any]:
    """
    The three owned keys as the API shape. Wrong-typed values read as null —
    the desktop's own rule (`as_str`/`as_bool`/`as_u64`).
    """
    model = document.get(KEY_MODEL)
    enabled = document.get(KEY_AUTO_COMPACT_ENABLED)
    window = document.get(KEY_AUTO_COMPACT_WINDOW)
    return {
        "model": model if isinstance(model, str) else None,
        "auto_compact_enabled": enabled if isinstance(enabled, bool) else None,
        "auto_compact_window": window if _reads_as_a_token_count(window) else None,
    }


def read_agent_settings(branch_root: Path) -> Dict[str, Any]:
    """One branch's three settings, or all-null when it has no file."""
    return agent_settings_view(read_object(branch_root / AGENT_SETTINGS_RELATIVE))


def write_agent_settings(branch_root: Path, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Patch one branch's claude settings, preserving every key BAUD does not own."""
    for field, value in patch.items():
        if field not in _AGENT_FIELDS:
            raise SettingsRefused(f"'{field}' is not a setting this door owns — the allowlist is the contract")
        file_key, expected = _AGENT_FIELDS[field]
        if value is None:
            continue
        if expected is int and isinstance(value, bool):
            raise SettingsRefused(f"'{field}' wants a number, not a boolean")
        if not isinstance(value, expected):
            raise SettingsRefused(f"'{field}' wants a {expected.__name__}, got {type(value).__name__}")
        if field == "auto_compact_window" and value <= 0:
            raise SettingsRefused("'auto_compact_window' must be a positive token count")

    path = branch_root / AGENT_SETTINGS_RELATIVE
    document = read_object(path)
    # Three-state: absent touches nothing, null removes, a value sets.
    for field, value in patch.items():
        file_key, _ = _AGENT_FIELDS[field]
        if value is None:
            document.pop(file_key, None)
        else:
            document[file_key] = value
    write_atomically(path, document)

    json_handler.log_operation(
        "host_api_agent_settings_written",
        {"branch": branch_root.name, "fields": sorted(patch.keys())},
    )
    logger.info("[host_api] agent settings patched for %s (%s)", branch_root.name, ", ".join(sorted(patch)))
    return agent_settings_view(document)


def read_baud_settings(project_root: Path) -> Dict[str, Any]:
    """BAUD's own document, whole and opaque — absence reads as {}."""
    return read_object(project_root / BAUD_SETTINGS_RELATIVE)


def write_baud_settings(project_root: Path, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow-merge a patch into BAUD's own document and hand the result back."""
    if not isinstance(patch, dict):
        raise SettingsRefused("the baud settings patch must be a JSON object")

    path = project_root / BAUD_SETTINGS_RELATIVE
    document = read_object(path)
    for key, value in patch.items():
        if value is None:
            document.pop(key, None)
        else:
            document[key] = value
    write_atomically(path, document)

    json_handler.log_operation("host_api_baud_settings_written", {"keys": sorted(patch.keys())})
    logger.info("[host_api] baud settings merged (%s)", ", ".join(sorted(patch)))
    return document


def hooks_sound_get() -> bool:
    """Whether hook sounds are currently on."""
    return not hooks_sound.is_muted()


def hooks_sound_set(active: bool) -> bool:
    """Flip hook sounds through @hooks' registered command."""
    verb = HOOKS_SOUND_ON if active else HOOKS_SOUND_OFF
    command = HOOKS_SOUND_DOOR + [verb]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=HOOKS_SOUND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.error("[host_api] hooks sound door failed: %s", e)
        raise SettingsUnavailable(f"Could not reach the hooks sound door: {e}") from e

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SettingsUnavailable(f"The hooks sound door refused: {detail}")

    # The exit code is not evidence (an unknown verb exits zero too): read back.
    settled = hooks_sound_get()

    if settled != active:
        raise SettingsUnavailable(
            f"The hooks sound door answered but hook sounds are still "
            f"{'on' if settled else 'off'} — nothing was changed"
        )

    json_handler.log_operation("host_api_hooks_sound_set", {"active": active})

    return settled
