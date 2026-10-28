# =================== AIPass ====================
# Name: provider_wire.py
# Description: Auto-wire provider settings from manifest into user config
# Version: 1.10.0
# Created: 2026-07-11
# Modified: 2026-10-28
# =============================================

"""provider_wire — auto-wire provider settings.

Hooks are strip-and-readd (stale bridge entries go); env, permissions and the
top-level settings scalars are additive only: a value the user set is reported,
never overwritten. The manifest is the single source; this file holds no defaults.
``cli.codex`` hooks merge into the user-level Codex hooks.json, AIPass groups first. Both
doors (setup.sh, doctor --fix) back up before the write, receipt after. setup.sh alone
also sets the Codex config pins, line by line, keeping every other line of config.toml.
Both doors copy the OpenCode plugin byte-equal into opencode_plugin_path(), backup and receipt the same.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Optional

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.settings_backup import (
    DOOR_DOCTOR_FIX,
    DOOR_SETUP_SH,
    BackupRecord,
    SettingsBackupError,
    backup_before_write,
    sha256_of,
    write_receipt,
)

HOOK_DESCRIPTIONS: Dict[str, str] = {
    "pre_edit_gate.py": "blocks edits outside agent's branch",
    "subagent_stop_gate.py": "validates agent output on exit",
    "auto_fix_diagnostics.py": "auto-fixes lint issues after edits",
    "global_prompt_loader.py": "injects branch context on each turn",
    "identity_injector.py": "injects agent identity on each turn",
    "email_notification.py": "notifies on incoming agent mail",
    "branch_prompt_loader.py": "loads branch-specific prompts",
    "pre_compact.py": "saves state before context compaction",
}

ENV_DESCRIPTIONS: Dict[str, str] = {
    "AIPASS_HOME": "tells agents where AIPass lives",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "prevents conflict with .trinity/ memory system",
}

BRIDGE_MARKER = "bridges/claude.py"

SETTINGS_SLOT = "settings"

SETTINGS_DESCRIPTIONS: Dict[str, str] = {
    "includeGitInstructions": "drops the ~4k-char gitStatus block Claude Code injects every session",
}

WIRE_COMMAND = "aipass doctor --fix"

MSYS_ENV_KEY = "PYTHONUTF8"
MSYS_ENV_VALUE = "1"

STATE_SET = "set"
STATE_MISSING = "missing"
STATE_DIFFERENT = "different"

_SCALAR_TYPES = (bool, int, float, str)


class SettingsGap(NamedTuple):
    """One manifest settings key measured against the provider settings file."""

    key: str
    wanted: Any
    actual: Any
    state: str  # STATE_SET | STATE_MISSING | STATE_DIFFERENT


def manifest_settings(manifest: dict) -> Dict[str, Any]:
    """The top-level provider-settings keys the manifest wants, and their values.

    Scalars only: a nested block typed into the slot is dropped, never merged.
    """
    slot = manifest.get("cli", {}).get("claude", {}).get(SETTINGS_SLOT, {})
    if not isinstance(slot, dict):
        logger.warning(
            "[provider_wire] manifest %s slot is %s, not a map — ignored", SETTINGS_SLOT, type(slot).__name__
        )
        return {}
    wanted: Dict[str, Any] = {}
    for key, value in slot.items():
        if isinstance(value, _SCALAR_TYPES):
            wanted[key] = value
        else:
            logger.warning("[provider_wire] manifest %s.%s is not a scalar — skipped", SETTINGS_SLOT, key)
    return wanted


def _same_value(actual: Any, wanted: Any) -> bool:
    """True when the provider's value is the manifest's value, false/0 kept distinct."""
    if isinstance(actual, bool) != isinstance(wanted, bool):
        return False
    return actual == wanted


def settings_gaps(wanted: Dict[str, Any], settings: dict) -> List[SettingsGap]:
    """Per-key diff: what the manifest wants vs what the provider settings file has.

    The one reader both lanes use, so `aipass doctor` reports exactly what the wire does.
    """
    gaps: List[SettingsGap] = []
    for key, value in wanted.items():
        if key not in settings:
            gaps.append(SettingsGap(key, value, None, STATE_MISSING))
            continue
        actual = settings[key]
        state = STATE_SET if _same_value(actual, value) else STATE_DIFFERENT
        gaps.append(SettingsGap(key, value, actual, state))
    return gaps


def _merge_settings_scalars(settings: dict, wanted: Dict[str, Any]) -> List[str]:
    """Set the manifest's scalars that are absent; report, never overwrite, the rest."""
    actions: List[str] = []
    for gap in settings_gaps(wanted, settings):
        if gap.state == STATE_MISSING:
            settings[gap.key] = gap.wanted
            actions.append(f"Set {gap.key}={json.dumps(gap.wanted)}")
        elif gap.state == STATE_DIFFERENT:
            actions.append(
                f"Kept your {gap.key}={json.dumps(gap.actual)} "
                f"(manifest wants {json.dumps(gap.wanted)}) — your value wins, nothing overwritten"
            )
    return actions


def platform_bridge_command(command: str, os_name: Optional[str] = None) -> str:
    """Write-time OS transform for the venv interpreter path (manifest stays POSIX-canonical).

    Public: doctor's manifest check verifies with this same transform (write and verify
    must agree). *os_name* is a test seam; product callers pass None.
    """
    # Windows hooks run under Git Bash ($AIPASS_HOME still expands) but the venv is .venv/Scripts.
    if (os.name if os_name is None else os_name) == "nt":
        return command.replace("/.venv/bin/python3", "/.venv/Scripts/python.exe")
    return command


def _build_manifest_hook_entries(manifest_hooks: List[dict]) -> Dict[str, List[dict]]:
    """Build the settings.json hook-entry shape per event from manifest hook rows."""
    fresh: Dict[str, List[dict]] = {}
    for hook in manifest_hooks:
        command = platform_bridge_command(hook.get("command", ""))
        event = hook.get("event", "")
        if not command or not event:
            continue
        cmd_entry: Dict[str, object] = {"type": "command", "command": command}
        if hook.get("timeout"):
            cmd_entry["timeout"] = hook["timeout"]
        wrapper: Dict[str, object] = {}
        if hook.get("matcher"):
            wrapper["matcher"] = hook["matcher"]
        wrapper["hooks"] = [cmd_entry]
        fresh.setdefault(event, []).append(wrapper)
    return fresh


def _strip_and_readd_hooks(
    existing_hooks: Dict[str, list], manifest_hooks: List[dict]
) -> "tuple[Dict[str, list], List[str]]":
    """Strip every AIPass bridge-marked hook entry, then re-add the manifest's current set.

    An additive merge left an old-shape bridge entry beside the fresh one and the hook
    fired twice. Non-bridge (user) hooks are preserved untouched.
    """
    fresh = _build_manifest_hook_entries(manifest_hooks)
    actions: List[str] = []
    merged: Dict[str, list] = {}
    for event in sorted(set(existing_hooks) | set(fresh)):
        stale_count = sum(1 for e in existing_hooks.get(event, []) if BRIDGE_MARKER in json.dumps(e))
        user_entries = [e for e in existing_hooks.get(event, []) if BRIDGE_MARKER not in json.dumps(e)]
        event_fresh = fresh.get(event, [])
        combined = event_fresh + user_entries
        if not combined:
            actions.append(f"Dropped orphaned hook event (no live entries): {event}")
            continue
        merged[event] = combined
        if event_fresh:
            note = f" (replaced {stale_count} stale)" if stale_count else ""
            actions.append(f"Refreshed {event}: {len(event_fresh)} bridge hook(s){note}")
    return merged, actions


def _is_msys_shell(environ: Optional[Mapping[str, str]] = None) -> bool:
    """True under Git Bash / MSYS / MinGW on Windows — the one place PYTHONUTF8 belongs."""
    env = os.environ if environ is None else environ
    shell = env.get("MSYSTEM", "") + env.get("OSTYPE", "")
    return "MSYS" in shell or "msys" in shell or "MINGW" in shell


def _merge_env(settings: dict, claude_section: dict, manifest_path: Path) -> List[str]:
    """Additive env merge: the manifest's env keys the file lacks, plus PYTHONUTF8 under MSYS.

    The manifest has no guard syntax, so the wire owns the PYTHONUTF8 conditional
    (Rich output in Windows hook processes needs it).
    """
    actions: List[str] = []
    wanted: Dict[str, str] = {}
    repo_root = str(manifest_path.parent.parent)
    project_root = str(Path.cwd())
    for key, value in claude_section.get("env", {}).items():
        wanted[key] = value.replace("{{REPO_ROOT}}", repo_root).replace("{{PROJECT_ROOT}}", project_root)
    if _is_msys_shell():
        wanted.setdefault(MSYS_ENV_KEY, MSYS_ENV_VALUE)
    if not wanted:
        return actions
    env_block = settings.setdefault("env", {})
    for key, resolved in wanted.items():
        if key not in env_block:
            env_block[key] = resolved
            actions.append(f"Set env {key}={resolved}")
    return actions


def _repoint_aipass_home(settings: dict, manifest_path: Path) -> List[str]:
    """Install only: point env.AIPASS_HOME at the tree being installed, whatever it said.

    doctor --fix never calls this: a fix from a second checkout must not take the home
    from the first.
    """
    env_block = settings.get("env")
    if not isinstance(env_block, dict) or "AIPASS_HOME" not in env_block:
        return []
    repo_root = str(manifest_path.parent.parent)
    old = env_block["AIPASS_HOME"]
    if old == repo_root:
        return []
    env_block["AIPASS_HOME"] = repo_root
    return [f"Re-pointed AIPASS_HOME {old} -> {repo_root}"]


def _merge_permissions(settings: dict, claude_section: dict) -> List[str]:
    """Additive deny + ask merge: a manifest rule the file lacks is appended, none removed."""
    actions: List[str] = []
    manifest_perms = claude_section.get("permissions", {})
    manifest_deny = manifest_perms.get("deny", [])
    manifest_ask = manifest_perms.get("ask", [])
    if not (manifest_deny or manifest_ask):
        return actions
    permissions = settings.setdefault("permissions", {})
    for kind, rules in (("deny", manifest_deny), ("ask", manifest_ask)):
        current = permissions.setdefault(kind, [])
        existing = set(current)
        for rule in rules:
            if rule not in existing:
                current.append(rule)
                existing.add(rule)
                actions.append(f"Added {kind} rule: {rule}")
    return actions


def _write_with_receipt(
    settings_path: Path,
    settings: dict,
    record: BackupRecord,
    actions: List[str],
    updated_line: str,
    consent: Optional[str] = None,
) -> None:
    """Write the settings a door merged, then its receipt; the backup lines go in *actions*.

    The fleet writer returns False instead of raising; that becomes SettingsBackupError, no receipt.
    """
    if record.backup is not None:
        actions.append(f"Backed up settings to {record.backup}")
    else:
        actions.append("No settings file yet — nothing to back up")
    if not json_handler.write_json(settings_path, settings):
        logger.error("[provider_wire] settings write failed at %s; no receipt written", settings_path)
        raise SettingsBackupError(f"settings write failed at {settings_path}; no receipt written")
    actions.append(updated_line)
    summary = ([f"consent: {consent}"] if consent else []) + actions
    receipt = write_receipt(record, sha256_of(settings_path), summary)
    actions.append(f"Receipt: {receipt}")


class SettingsPlan(NamedTuple):
    """A change to the provider settings file, computed and not yet written.

    *actions* are past tense (reported after the write); *planned* only the lines that
    change the file, in planned tense; *notes* the lines that change nothing.
    """

    settings_path: Path
    before: dict
    after: dict
    actions: List[str]
    planned: List[str]
    notes: List[str]
    door: str
    updated_line: str


_REFRESHED = re.compile(
    r"^Refreshed (?P<event>\S+): (?P<n>\d+) bridge hook\(s\)(?: \(replaced (?P<stale>\d+) stale\))?$"
)

_PLANNED_PREFIXES = (
    ("Added deny rule: ", "Add deny rule "),
    ("Added ask rule: ", "Add ask rule "),
    ("Dropped orphaned hook event (no live entries): ", "Drop orphaned hook event "),
    ("Set ", "Set "),
)


def _planned_line(action: str) -> Optional[str]:
    """The planned-tense form of a past-tense action line; None for a line that changes nothing."""
    refreshed = _REFRESHED.match(action)
    if refreshed:
        stale = f" (replace {refreshed['stale']} stale)" if refreshed["stale"] else ""
        return f"Re-add {refreshed['n']} bridge hook(s) in {refreshed['event']}{stale}"
    for past, planned in _PLANNED_PREFIXES:
        if action.startswith(past):
            return planned + action[len(past) :]
    return None


def _make_plan(
    settings_path: Path, before: dict, after: dict, actions: List[str], door: str, updated_line: str
) -> SettingsPlan:
    """Split a door's action lines into the planned changes and the notes."""
    planned: List[str] = []
    notes: List[str] = []
    for action in actions:
        line = _planned_line(action)
        if line is None:
            notes.append(action)
        else:
            planned.append(line)
    return SettingsPlan(settings_path, before, after, actions, planned, notes, door, updated_line)


def _serialized(settings: dict) -> List[str]:
    """The settings as the fleet json writer lays them out, one entry per line."""
    return json.dumps(settings, indent=2, ensure_ascii=False).splitlines()


def settings_diff(before: dict, after: dict, label: str = "settings.json") -> List[str]:
    """A unified diff of the settings as they are against the settings as they would land."""
    return list(
        difflib.unified_diff(_serialized(before), _serialized(after), f"{label} (now)", f"{label} (after)", lineterm="")
    )


def _read_settings(settings_path: Path) -> dict:
    """The settings file as a dict; {} when absent or empty. Raises rather than plan from {} over a typo."""
    if not settings_path.exists() or not settings_path.read_text(encoding="utf-8").strip():
        return {}
    settings = json_handler.read_json(settings_path)
    if not isinstance(settings, dict):
        raise SettingsBackupError(f"settings unreadable at {settings_path} (not a JSON object) — not touching it")
    return settings


def plan_wire_provider(manifest_path: Path, settings_path: Optional[Path] = None) -> Optional[SettingsPlan]:
    """What the doctor's wire door would write, computed without writing.

    None when the manifest is unreadable or has no ``cli.claude`` section. A hook refresh
    that leaves an event as it was is not a change, so a fully wired file plans nothing.
    """
    manifest = json_handler.read_json(manifest_path)
    if manifest is None:
        return None
    claude_section = manifest.get("cli", {}).get("claude", {})
    if not claude_section:
        return None

    if settings_path is None:
        settings_path = Path.home() / ".claude" / "settings.json"
    # resolve(): the atomic replace would swap a symlinked settings.json for a regular file.
    settings_path = settings_path.resolve()
    settings = _read_settings(settings_path)
    before = copy.deepcopy(settings)

    existing_hooks = settings.get("hooks", {}) or {}
    merged_hooks, hook_actions = _strip_and_readd_hooks(existing_hooks, claude_section.get("hooks", []))
    settings["hooks"] = merged_hooks
    unchanged = {event for event in merged_hooks if existing_hooks.get(event) == merged_hooks[event]}
    actions = [a for a in hook_actions if not any(a.startswith(f"Refreshed {e}:") for e in unchanged)]

    actions.extend(_merge_env(settings, claude_section, manifest_path))
    actions.extend(_merge_permissions(settings, claude_section))
    actions.extend(_merge_settings_scalars(settings, manifest_settings(manifest)))
    return _make_plan(settings_path, before, settings, actions, DOOR_DOCTOR_FIX, "Updated ~/.claude/settings.json")


CODEX_BRIDGE_MARK = "src/aipass/hooks/apps/handlers/bridges/codex.py"
# (key path, its table header or None for top level); each must read false.
CODEX_PINS = (
    (("features", "memories"), "[features]"),
    (("include_collaboration_mode_instructions",), None),
    (("features", "collaboration_modes"), "[features]"),
    (("tools", "experimental_request_user_input", "enabled"), "[tools.experimental_request_user_input]"),
)
_TABLE_HEADER = re.compile(r"^\s*\[")


def codex_home() -> Path:
    """$CODEX_HOME when set, else ~/.codex."""
    home = os.environ.get("CODEX_HOME")
    return Path(home) if home else Path.home() / ".codex"


def codex_config_path() -> Path:
    """Codex's config.toml in codex_home()."""
    return codex_home() / "config.toml"


def read_codex_config(path: Path) -> tuple[dict, str]:
    """(the parsed config, '') or ({}, why it could not be read). Read-only: the owner edits it."""
    try:
        import tomllib  # type: ignore[import-not-found]  # stdlib 3.11+, absent on 3.10
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            logger.warning("[provider_wire] no tomllib and no tomli: config.toml unread below Python 3.11")
            return {}, "reading config.toml needs Python 3.11+ or the tomli package"
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")), ""
    except FileNotFoundError:
        logger.info("[provider_wire] no codex config at %s", path)
        return {}, f"{path} missing"
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("[provider_wire] codex config unreadable: %s: %s", path, exc)
        return {}, f"{path} unreadable: {exc}"


def codex_pin_value(config: dict, keys: tuple) -> Any:
    """The value at *keys* in a parsed config.toml; None when any step is absent."""
    value: Any = config
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _set_pin_line(lines: List[str], keys: tuple, table: Optional[str]) -> List[str]:
    """*lines* with ``<key> = false`` in *table*'s section (top level when None), replacing a line that sets it."""
    line = f"{keys[-1]} = false"
    assigns = re.compile(rf"^\s*{re.escape(keys[-1])}\s*=")
    headers = [i for i, text in enumerate(lines) if _TABLE_HEADER.match(text)]
    if table is None:
        start, end = 0, headers[0] if headers else len(lines)
    else:
        own = [i for i in headers if lines[i].split("#")[0].strip() == table]
        if not own:
            return [*lines, *([""] if lines and lines[-1].strip() else []), table, line]
        start, end = own[0] + 1, next((i for i in headers if i > own[0]), len(lines))
    for i in range(start, end):
        if assigns.match(lines[i]):
            return [*lines[:i], line, *lines[i + 1 :]]
    at = end if table is None else start
    return [*lines[:at], line, *lines[at:]]


def set_codex_pins(config_path: Path, door: str = DOOR_SETUP_SH) -> List[str]:
    """Set each CODEX_PINS key that does not read false, one line each; every other line is kept.

    Refuses (SettingsBackupError, nothing written) a config.toml it cannot parse, or one where
    the line edit breaks the file or leaves a pin unset (a dotted key, an inline table, a string)."""
    try:
        import tomllib  # type: ignore[import-not-found]  # stdlib 3.11+, absent on 3.10
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            logger.warning("[provider_wire] no tomllib and no tomli: Codex pins unset below Python 3.11")
            return ["Skipped the Codex config pins: setting them needs Python 3.11+ or the tomli package"]
    before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    try:
        config = tomllib.loads(before)
    except tomllib.TOMLDecodeError as exc:
        raise SettingsBackupError(f"{config_path} unreadable ({exc}) — not touching it") from exc
    lines, named = before.splitlines(), []
    for keys, table in CODEX_PINS:
        if codex_pin_value(config, keys) is not False:
            lines = _set_pin_line(lines, keys, table)
            named.append(".".join(keys))
    if not named:
        return []
    after = "\n".join(lines) + "\n"
    try:
        result = tomllib.loads(after)
    except tomllib.TOMLDecodeError as exc:
        raise SettingsBackupError(f"setting the Codex pins would break {config_path} — not touching it") from exc
    if any(codex_pin_value(result, k) is not False for k, _ in CODEX_PINS):
        raise SettingsBackupError(f"a line edit leaves the Codex pins unset in {config_path} — not touching it")
    record = backup_before_write(config_path, door)
    actions = [f"Backed up Codex config to {record.backup}"] if record.backup else []
    try:
        config_path.write_text(after, encoding="utf-8")
    except OSError as exc:
        logger.error("[provider_wire] codex config write failed at %s: %s", config_path, exc)
        raise SettingsBackupError(f"Codex config write failed at {config_path}; no receipt written") from exc
    actions.append(f"Set Codex pins in {config_path}: {', '.join(named)}")
    actions.append(f"Receipt: {write_receipt(record, sha256_of(config_path), actions)}")
    return actions


def refresh_codex(manifest_path: Path) -> List[str]:
    """setup.sh's Codex door: cli.codex merged into the user-level hooks.json, then the config pins.

    The hooks plan is the one doctor --fix applies, so the two doors cannot disagree."""
    actions: List[str] = []
    plan = plan_codex_hooks(manifest_path, DOOR_SETUP_SH)
    if plan is not None:
        actions.extend(apply_settings_plan(plan))
    actions.extend(set_codex_pins(codex_config_path(), DOOR_SETUP_SH))
    written = _read_settings(codex_hooks_path()).get("hooks", {})
    rows = sum(len(g.get("hooks", [])) for groups in written.values() for g in groups or [] if is_bridge_group(g))
    actions.append(f"Codex hooks: {rows} AIPass row(s) in {codex_hooks_path()}")
    json_handler.log_operation("refresh_codex", {"actions": len(actions)})
    return actions


def codex_hooks_path() -> Path:
    """The user-level Codex hooks file, which Codex reads from every cwd: codex_home()/hooks.json."""
    return codex_home() / "hooks.json"


def repo_codex_hooks_path(manifest_path: Path) -> Path:
    """The repo-level ``<repo root>/.codex/hooks.json``, the root taken from the manifest."""
    return manifest_path.parent.parent / ".codex" / "hooks.json"


def is_bridge_group(group: Any) -> bool:
    """Does this hook group run the AIPass Codex bridge?"""
    hooks = group.get("hooks", []) if isinstance(group, dict) else []
    return any(CODEX_BRIDGE_MARK in str(h.get("command", "")) for h in hooks if isinstance(h, dict))


def _foreign_part(group: Any) -> Optional[Any]:
    """The group with its bridge rows taken out; None when nothing else is left."""
    if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
        return group
    kept = [h for h in group["hooks"] if not (isinstance(h, dict) and CODEX_BRIDGE_MARK in str(h.get("command", "")))]
    return {**group, "hooks": kept} if kept else None


def merge_codex_hooks(before: dict, wanted: dict) -> dict:
    """*before* with its bridge rows replaced by *wanted*'s; every other row kept, behind them.

    Codex keys trust by ``<file>:<event>:<group>:<index>``, so AIPass groups go first in each
    event: a foreign group ahead would shift every AIPass key and untrust it."""
    merged = copy.deepcopy(before)
    old = before.get("hooks")
    old = old if isinstance(old, dict) else {}
    hooks: Dict[str, Any] = {}
    for event in [*wanted["hooks"], *(e for e in old if e not in wanted["hooks"])]:
        foreign = [part for g in old.get(event, []) or [] if (part := _foreign_part(g)) is not None]
        groups = copy.deepcopy(wanted["hooks"].get(event, [])) + foreign
        if groups:
            hooks[event] = groups
    merged["hooks"] = hooks
    return merged


def repo_codex_double_fire(manifest_path: Path) -> Optional[Path]:
    """The repo-level hooks file when it still holds bridge rows, which Codex fires beside the user-level ones."""
    path = repo_codex_hooks_path(manifest_path)
    try:
        doc = _read_settings(path)
    except SettingsBackupError as exc:
        logger.warning("[provider_wire] repo codex hooks unreadable, double-fire unknown: %s", exc)
        return None
    events = doc.get("hooks")
    events = events if isinstance(events, dict) else {}
    return path if any(is_bridge_group(g) for groups in events.values() for g in groups or []) else None


def codex_trust_keys(hooks_path: Path, wanted: dict) -> List[str]:
    """The ``[hooks.state]`` keys Codex trusts the AIPass rows under, once they sit first."""
    keys = []
    for event, groups in wanted["hooks"].items():
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()
        for g, group in enumerate(groups):
            keys.extend(f"{hooks_path}:{snake}:{g}:{i}" for i in range(len(group["hooks"])))
    return keys


def codex_hooks_document(manifest: dict) -> Optional[dict]:
    """The whole Codex hooks file the manifest's ``cli.codex.hooks`` rows make; None when it has none.

    Codex reads Claude's hook shape, so the Claude entry builder serves both.
    """
    rows = manifest.get("cli", {}).get("codex", {}).get("hooks", [])
    if not rows:
        return None
    return {"hooks": _build_manifest_hook_entries(rows)}


def plan_codex_hooks(manifest_path: Path, door: str = DOOR_DOCTOR_FIX) -> Optional[SettingsPlan]:
    """Merge ``cli.codex`` into the user-level Codex hooks file; None when it already matches.

    No rows plans nothing, rather than empty a file the manifest has not caught up with."""
    manifest = json_handler.read_json(manifest_path)
    if manifest is None:
        return None
    wanted = codex_hooks_document(manifest)
    if wanted is None:
        return None
    codex_path = codex_hooks_path()
    before = _read_settings(codex_path)
    after = merge_codex_hooks(before, wanted)
    if before == after:
        return None
    count = sum(len(entries) for entries in wanted["hooks"].values())
    return SettingsPlan(
        codex_path,
        before,
        after,
        [f"Wrote {count} Codex hook(s) from cli.codex"],
        [f"Write {count} Codex hook(s) from cli.codex into {codex_path}"],
        [],
        door,
        f"Updated {codex_path}",
    )


def apply_settings_plan(plan: SettingsPlan, door: Optional[str] = None, consent: Optional[str] = None) -> List[str]:
    """Write a plan through its backed-up door: backup, write, receipt. Returns the action lines."""
    actions = list(plan.actions)
    if _read_settings(plan.settings_path) != plan.before:
        raise SettingsBackupError(f"settings changed since planned at {plan.settings_path} — re-run")
    record = backup_before_write(plan.settings_path, door or plan.door)
    _write_with_receipt(plan.settings_path, copy.deepcopy(plan.after), record, actions, plan.updated_line, consent)
    json_handler.log_operation("apply_settings_plan", {"door": door or plan.door, "actions": len(actions)})
    return actions


def refresh_provider_hooks(manifest_path: Path, settings_path: Optional[Path] = None) -> List[str]:
    """Write the manifest's Claude wiring into ~/.claude/settings.json; refresh_codex is Codex's door.

    setup.sh is the only caller; doctor --fix plans the same writes. Raises on an
    unreadable manifest rather than leave stale wiring in place."""
    manifest = json_handler.read_json(manifest_path)
    if manifest is None:
        raise FileNotFoundError(f"provider manifest unreadable: {manifest_path}")
    manifest_hooks = manifest.get("cli", {}).get("claude", {}).get("hooks", [])

    if settings_path is None:
        settings_path = Path.home() / ".claude" / "settings.json"
    settings_path = settings_path.resolve()
    settings = _read_settings(settings_path)

    merged_hooks, actions = _strip_and_readd_hooks(settings.get("hooks", {}) or {}, manifest_hooks)
    settings["hooks"] = merged_hooks
    claude_section = manifest.get("cli", {}).get("claude", {})
    actions.extend(_merge_env(settings, claude_section, manifest_path))
    actions.extend(_repoint_aipass_home(settings, manifest_path))
    actions.extend(_merge_permissions(settings, claude_section))
    actions.extend(_merge_settings_scalars(settings, manifest_settings(manifest)))

    record = backup_before_write(settings_path, DOOR_SETUP_SH)
    _write_with_receipt(
        settings_path, settings, record, actions, "Updated ~/.claude/settings.json (hooks, env, permissions, settings)"
    )
    json_handler.log_operation("refresh_provider_hooks", {"actions": len(actions)})
    return actions


OPENCODE_BRIDGE_MARK = "src/aipass/hooks/apps/handlers/bridges/opencode.py"
OPENCODE_PLUGIN_REL = Path("src") / "aipass" / "hooks" / "apps" / "handlers" / "bridges" / "opencode_plugin.ts"


def opencode_config_dir() -> Path:
    """Where OpenCode reads its config and plugins: $XDG_CONFIG_HOME/opencode, else ~/.config/opencode."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "opencode"


def opencode_plugin_path() -> Path:
    """The installed plugin OpenCode loads for every project: opencode_config_dir()/plugins/aipass.ts."""
    return opencode_config_dir() / "plugins" / "aipass.ts"


def opencode_plugin_source(manifest_path: Path) -> Path:
    """The hooks branch's plugin source in the repo the manifest sits in."""
    return manifest_path.parent.parent / OPENCODE_PLUGIN_REL


def opencode_plugin_state(manifest_path: Path) -> Optional[str]:
    """STATE_SET when the installed plugin is byte-equal to the source, else MISSING or DIFFERENT.

    None when the manifest has no cli.opencode bridge rows or the source is absent: nothing to install."""
    manifest = json_handler.read_json(manifest_path)
    rows = manifest.get("cli", {}).get("opencode", {}).get("hooks", []) if isinstance(manifest, dict) else []
    if not any(OPENCODE_BRIDGE_MARK in str(row.get("command", "")) for row in rows if isinstance(row, dict)):
        return None
    source = opencode_plugin_source(manifest_path)
    if not source.is_file():
        logger.warning("[provider_wire] OpenCode plugin source missing at %s", source)
        return None
    plugin = opencode_plugin_path()
    if not plugin.is_file():
        return STATE_MISSING
    return STATE_SET if plugin.read_bytes() == source.read_bytes() else STATE_DIFFERENT


def opencode_plugin_plan(manifest_path: Optional[Path]) -> List[str]:
    """The planned line for a missing or stale OpenCode plugin; [] when it matches or is not wanted."""
    if manifest_path is None or opencode_plugin_state(manifest_path) in (None, STATE_SET):
        return []
    return [f"Install the OpenCode plugin: cp {opencode_plugin_source(manifest_path)} {opencode_plugin_path()}"]


def install_opencode_plugin(manifest_path: Path, door: str = DOOR_SETUP_SH, consent: Optional[str] = None) -> List[str]:
    """Copy the plugin byte-equal into opencode_plugin_path(): backup first, receipt after. [] when it matches."""
    if opencode_plugin_state(manifest_path) in (None, STATE_SET):
        return []
    plugin = opencode_plugin_path()
    plugin.parent.mkdir(parents=True, exist_ok=True)
    record = backup_before_write(plugin, door)
    actions = [f"Backed up the OpenCode plugin to {record.backup}"] if record.backup else []
    try:
        plugin.write_bytes(opencode_plugin_source(manifest_path).read_bytes())
    except OSError as exc:
        logger.error("[provider_wire] OpenCode plugin write failed at %s: %s", plugin, exc)
        raise SettingsBackupError(f"OpenCode plugin write failed at {plugin}; no receipt written") from exc
    actions.append(f"Installed the OpenCode plugin at {plugin}")
    summary = ([f"consent: {consent}"] if consent else []) + actions
    actions.append(f"Receipt: {write_receipt(record, sha256_of(plugin), summary)}")
    json_handler.log_operation("install_opencode_plugin", {"door": door, "actions": len(actions)})
    return actions
