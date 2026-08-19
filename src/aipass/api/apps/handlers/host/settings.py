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
    @hooks' mute switch                    - a flag FILE, not a setting, and
        NOT this branch's to write. Where it lives and how it is flipped are
        @hooks' knowledge; this lane asks their door and reads their answer.
        Both directions stay idempotent because two windows (or an operator
        at the CLI) may race on the same switch.

Read-then-error-then-write everywhere: a file that exists but does not parse
as a JSON object REFUSES both reads and writes before a single byte moves -
showing empty dials for a file that sets values is a lie, and the write path
must never treat unreadable as blank (the desktop's own doctrine, kept).
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict

from aipass.prax import logger

# @hooks' own module for the mute switch. Imported rather than mirrored: the
# flag's location is declared once, in their tree, and a copy here would be a
# second truth that goes stale the first time they move it.
from aipass.hooks.apps import sound as hooks_sound
from aipass.api.apps.handlers.json import json_handler

# ==============================================
# CONSTANTS
# ==============================================

AGENT_SETTINGS_RELATIVE = Path(".claude") / "settings.local.json"
BAUD_SETTINGS_RELATIVE = Path(".aipass") / "baud.settings.json"

# @hooks' door for the machine-wide mute switch. The registered command, the
# same one an operator types — see the flip below for why its exit code is not
# taken as evidence.
HOOKS_SOUND_DOOR = ["drone", "@hooks", "hooksound"]
HOOKS_SOUND_ON = "on"
HOOKS_SOUND_OFF = "off"
HOOKS_SOUND_TIMEOUT_SECONDS = 30

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
    except FileNotFoundError:
        # Nothing is there yet. That is a fresh branch, not a fault, and it is
        # the ONLY OSError that reads as blank — see below.
        #
        # NotADirectoryError used to be let through here too, and the
        # conformance corpus ruled it out (FPLAN-0438 R3, divergence 2; rust
        # already refused). A missing DIRECTORY on the way to the file means
        # nobody has written settings yet. A FILE standing where a directory
        # belongs means the tree is broken — reading that as 'no settings yet'
        # invites a patch to write a document into a path that cannot hold one.
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


def _reads_as_a_token_count(value: Any) -> bool:
    """
    Whether a stored value can be shown on the window dial.

    The desktop reads this field with as_u64, so the mirror is UNSIGNED: a
    negative is not a small number here, it is a value the other face declines
    outright, and a view that passed -5 through would put a token count on a
    dial that cannot mean one (FPLAN-0438 R3, divergence 5 — rust was the
    strict side and this lane was not).

    Zero stays readable on purpose. It is a representable u64, so a file
    holding it reports it honestly; the refusal on zero belongs to the WRITE
    path, where the value is being created rather than reported.

    Args:
        value: Whatever the file had under the window key.

    Returns:
        True when the dial can show it.

    Note:
        bool is excluded FIRST because a Python bool is also an int — without
        that, `true` would arrive at the face as the number 1.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


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
        "auto_compact_enabled": enabled if isinstance(enabled, bool) else None,
        "auto_compact_window": window if _reads_as_a_token_count(window) else None,
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


def hooks_sound_get() -> bool:
    """
    Whether hook sounds are currently on.

    Answered by @hooks' own is_muted(), not by this lane's idea of where their
    flag lives. Reading is not writing, so no subprocess is spent on it — but
    the KNOWLEDGE still comes from the owner, which is the half of the boundary
    that a local path check would quietly break.

    Inverted on purpose: sounds are ACTIVE when the flag is ABSENT, so every
    face's toggle reads as "hook sounds: on" rather than as a double negative.

    Returns:
        True when sounds are active.
    """
    return not hooks_sound.is_muted()


def hooks_sound_set(active: bool) -> bool:
    """
    Flip hook sounds through @hooks' registered command.

    THIS USED TO WRITE THE FLAG BY HAND — a touch and an unlink on a path this
    module rebuilt for itself, while the docstring above named the door it was
    bypassing. Patrick's ruling settled it: api is api. The switch belongs to
    @hooks, so the flip is their command, the same one an operator types.

    Idempotent in both directions, unchanged: muting a muted fleet and unmuting
    an unmuted one are no-ops rather than errors, because two windows may race
    on the same switch.

    THE EXIT CODE IS NOT EVIDENCE, and that is measured rather than assumed:
    "hooksound sideways" prints "Unknown command" and exits ZERO, exactly like a
    real flip does. A lane that returned success on a zero would tell a face the
    fleet was muted while it kept ringing. So the switch is read back afterwards
    and a disagreement is a refusal — the only witness that cannot lie.

    Args:
        active: True to turn sounds on, False to mute.

    Returns:
        The state actually in force afterwards, read back from the flag.

    Raises:
        SettingsUnavailable: The door could not be run, took too long, refused,
            or answered without changing anything. Never a fallback to writing
            the flag here — becoming the thing this replaced, silently, is the
            one outcome worse than refusing.
    """
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

    settled = hooks_sound_get()

    if settled != active:
        raise SettingsUnavailable(
            f"The hooks sound door answered but hook sounds are still "
            f"{'on' if settled else 'off'} — nothing was changed"
        )

    json_handler.log_operation("host_api_hooks_sound_set", {"active": active})

    return settled
