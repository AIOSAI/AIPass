# =================== AIPass ====================
# Name: settings.py
# Description: Host API Settings Handler — the desktop's two gears, served
# Version: 1.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""
Host API Settings Handler

The phone's settings lane (DPLAN-0300): a faithful PYTHON MIRROR of @baud's
`settings.rs`, because the desktop gear and the phone gear must write the same
files the same way or the two faces drift on the operator's own config.

Two documents, one flag:

    <branch>/.claude/settings.local.json   - claude's own file. SURGICAL: only
        the three owned keys are ever named in a write, so every other key the
        operator keeps there survives untouched. The patch is three-state -
        an absent key touches nothing, null REMOVES, a value SETS - which is
        what lets "leave it alone" and "unset it" coexist in one shape.
    <project>/.aipass/baud.settings.json   - BAUD's own document, stored
        OPAQUE: shallow merge, null removes, nested objects replace whole.
    $TMPDIR/aipass-hooks-muted             - @hooks' own mute switch. A flag
        FILE, not a setting: the file is the single source of truth and both
        directions of the flip are idempotent, because two windows (or a
        `drone @hooks` toggle) may race on it.

Read-then-error-then-write everywhere: a file that exists but does not parse
as a JSON object REFUSES both reads and writes before a single byte moves -
showing empty dials for a file that sets values is a lie, and the write path
must never treat unreadable as blank (the desktop's own doctrine, kept).
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

# ==============================================
# CONSTANTS
# ==============================================

AGENT_SETTINGS_RELATIVE = Path(".claude") / "settings.local.json"
BAUD_SETTINGS_RELATIVE = Path(".aipass") / "baud.settings.json"

# @hooks' machine-wide mute switch — shared with the desktop and the CLI.
HOOKS_MUTE_FLAG = "aipass-hooks-muted"

# The three keys BAUD owns in claude's file — camelCase ON DISK (claude's own
# spelling), snake_case in the API shape (this house's spelling).
KEY_MODEL = "model"
KEY_AUTO_COMPACT_ENABLED = "autoCompactEnabled"
KEY_AUTO_COMPACT_WINDOW = "autoCompactWindow"

# API field -> (file key, type check). The allowlist IS the surgical guarantee.
_AGENT_FIELDS: Dict[str, tuple] = {
    "model": (KEY_MODEL, str),
    "auto_compact_enabled": (KEY_AUTO_COMPACT_ENABLED, bool),
    "auto_compact_window": (KEY_AUTO_COMPACT_WINDOW, int),
}


class SettingsRefused(Exception):
    """The caller's request cannot be honoured as asked — their 400."""


class SettingsUnavailable(Exception):
    """This host could not serve the settings — our 503."""


# ==============================================
# CORE FUNCTIONS
# ==============================================


def read_object(path: Path) -> Dict[str, Any]:
    """
    A settings file as a dict. Missing or empty reads as {} — a fresh branch
    has no settings and that is not a fault. Anything that exists but is not
    a JSON object is an ERROR, never blank (see module docstring).
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        # Nothing is there yet. That is a fresh branch, not a fault, and it is
        # the ONLY OSError that reads as blank — see below.
        #
        # Said out loud even so. It is the one branch here that answers with a
        # document nobody wrote, and when a face shows every dial at absent the
        # first question is always whether the file was missing or unread. Debug
        # because it is the ordinary case, not because it does not matter.
        logger.debug("[host_api] no settings file at %s yet — reading as blank", path)
        return {}
    except OSError as e:
        # Everything else means something IS there and this process could not
        # read it: a permission bit, a directory in the file's place, a mount
        # that went away. Answering {} here would be the module docstring's own
        # forbidden move — a patch would then write a fresh document over
        # settings that were merely unreadable, and the loss would be silent.
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
    """
    Remove a staged file that never made it into place.

    Called only while another exception is travelling, so this one is REPORTED
    rather than raised: a lost temp file is survivable, and re-raising here
    would replace the reason the write actually failed with a footnote about
    the cleanup. What must not happen is losing the fact — a stray temp file in
    .claude/ reads as somebody's lost config, and an operator seeing one
    deserves the line that explains it.
    """
    try:
        os.unlink(staged)
    except OSError as e:
        logger.warning("[host_api] staged settings file %s could not be removed: %s", staged, e)


def _replace_through_a_staged_file(directory: Path, path: Path, document: Dict[str, Any]) -> None:
    """
    Write the document beside its destination, then rename it over.

    BaseException, not Exception: a KeyboardInterrupt or a MemoryError mid-write
    leaves the same orphan on disk as a plain failure does, and the staged file
    must never survive either way.
    """
    descriptor, staged = tempfile.mkstemp(dir=str(directory), prefix=".baud-settings-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(staged, path)
    except BaseException:
        _discard(staged)
        raise


def write_atomically(path: Path, document: Dict[str, Any]) -> None:
    """
    Replace a settings file in one step: temp file in the SAME directory (so
    the rename stays on one filesystem and is atomic), then rename over. A
    reader sees the old file whole or the new one whole, never a torn half.

    Python's json keeps insertion order, so a one-key change does not
    reshuffle a document somebody else wrote — same property the desktop
    builds serde with `preserve_order` for.
    """
    directory = path.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _replace_through_a_staged_file(directory, path, document)
    except OSError as e:
        logger.error("[host_api] could not write settings at %s: %s", path, e)
        raise SettingsUnavailable(f"Could not write '{path.name}': {e}") from e


def agent_settings_view(document: Dict[str, Any]) -> Dict[str, Any]:
    """
    The three owned keys as the API shape. Wrong-typed values read as null —
    the desktop's own rule (`as_str`/`as_bool`/`as_u64`): a dial cannot show
    a value it does not understand, and null is the honest position for it.
    """
    model = document.get(KEY_MODEL)
    enabled = document.get(KEY_AUTO_COMPACT_ENABLED)
    window = document.get(KEY_AUTO_COMPACT_WINDOW)
    return {
        "model": model if isinstance(model, str) else None,
        # bool is checked FIRST below because a Python bool is also an int —
        # without the order, `true` would leak into the window field's type.
        "auto_compact_enabled": enabled if isinstance(enabled, bool) else None,
        "auto_compact_window": window if isinstance(window, int) and not isinstance(window, bool) else None,
    }


def read_agent_settings(branch_root: Path) -> Dict[str, Any]:
    """One branch's three settings, or all-null when it has no file."""
    return agent_settings_view(read_object(branch_root / AGENT_SETTINGS_RELATIVE))


def write_agent_settings(branch_root: Path, patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    Patch one branch's claude settings, preserving every key BAUD does not own.

    Args:
        branch_root: The branch directory (already fenced by the caller).
        patch: Three-state, API-shaped. Only the three owned fields may
            appear; a present null removes, a present value sets, absent
            touches nothing.

    Returns:
        The three owned keys as they stand after the write.

    Raises:
        SettingsRefused: Unknown field, wrong-typed value, or a corrupt file.
        SettingsUnavailable: The write itself failed.
    """
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
    # Read-then-error-then-write: a parse failure returns before a byte moves.
    document = read_object(path)
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
    """
    Shallow-merge a patch into BAUD's own document and hand the result back.

    Top level only: a nested object in the patch REPLACES its counterpart
    rather than merging into it, so a caller can always say exactly what a
    subtree should become. Null removes — same rule as the desktop.
    """
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


def hooks_mute_flag() -> Path:
    """Where @hooks keeps the machine-wide mute switch."""
    return Path(tempfile.gettempdir()) / HOOKS_MUTE_FLAG


def hooks_sound_get(flag: Optional[Path] = None) -> bool:
    """Sounds are ACTIVE when the mute flag is ABSENT — inverted on purpose
    so every face's toggle reads as 'hook sounds: on'."""
    return not (flag or hooks_mute_flag()).exists()


def hooks_sound_set(active: bool, flag: Optional[Path] = None) -> bool:
    """
    Flip the flag toward `active`. Both directions are idempotent — muting a
    muted fleet and unmuting an unmuted one are no-ops, never errors, because
    two faces may race on the same file.
    """
    target = flag or hooks_mute_flag()
    try:
        if active:
            # missing_ok says the idempotence outright instead of catching it
            # after the fact: unmuting an unmuted fleet is the intended answer,
            # not an error that happens to be ignored.
            target.unlink(missing_ok=True)
        else:
            target.touch()
    except OSError as e:
        raise SettingsUnavailable(f"Could not flip the hooks mute flag: {e}") from e
    return hooks_sound_get(target)
