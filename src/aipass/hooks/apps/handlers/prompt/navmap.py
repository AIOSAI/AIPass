# =================== AIPass ====================
# Name: navmap.py
# Version: 1.3.0
# Description: Tier 1 navigation map — periodic prompt injection (UserPromptSubmit); edit-time cap warning (PostToolUse)
# Branch: hooks
# Layer: apps/handlers/prompt
# Created: 2026-06-18
# Modified: 2026-10-26
# =============================================

"""Loads .aipass/tier1_navmap.md — richer navigation map injected periodically — and warns when an edit leaves it over its cap."""

import importlib
import json
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

#: The per-fire budget the file's own header states; injection cuts near 10,000, with no warning at edit time.
NAVMAP_CHAR_CAP = 8000
NAVMAP_FILE = "tier1_navmap.md"
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
_SILENT = {"stdout": "", "exit_code": 0}


def load_content(hook_data: dict) -> str:
    """Read tier1_navmap.md content, unconditionally (no cadence gate)."""
    grounding_content = importlib.import_module("aipass.hooks.apps.modules.grounding_content")
    return grounding_content.load_navmap(hook_data)


def handle(hook_data: dict) -> dict:
    """Load tier1 navmap — periodic (cadence period 5) + turn 0 + post-compaction."""
    try:
        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        if not cadence.should_fire("navmap", hook_data):
            return {"stdout": "", "exit_code": 0}
    except Exception as exc:
        # The degraded fail mode (DPLAN-0347): a cadence that cannot answer withholds
        # this loader; the kernel fires alone and its banner names why.
        logger.warning(
            "[HOOKS] navmap DEGRADED loader=navmap: cadence check raised, so it is WITHHELD and the kernel "
            "fires alone until this is cured: %s",
            exc,
        )
        return {"stdout": "", "exit_code": 0}

    try:
        content = load_content(hook_data)
        if not content:
            return {"stdout": "", "exit_code": 0}
        return {"stdout": content, "exit_code": 0, "sound": "navmap"}

    except Exception as exc:
        logger.info("[HOOKS] navmap: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}


def _edited_navmaps(hook_data: dict) -> list[Path]:
    """The .aipass/tier1_navmap.md files this tool call wrote."""
    tool_name = hook_data.get("tool_name", "")
    tool_input = hook_data.get("tool_input") or {}
    if tool_name == "Bash":
        bash_writes = importlib.import_module("aipass.hooks.apps.modules.bash_writes")
        command = tool_input.get("command") or ""
        paths = [Path(path) for path, _how in bash_writes.write_targets(command, hook_data.get("cwd") or "")]
    elif tool_name in EDIT_TOOLS:
        paths = [Path(tool_input.get("file_path") or tool_input.get("notebook_path") or "")]
    else:
        return []
    return [path for path in paths if path.name == NAVMAP_FILE and path.parent.name == ".aipass" and path.is_file()]


def handle_edit(hook_data: dict) -> dict:
    """PostToolUse: say, with the count, when an edit leaves a navmap over NAVMAP_CHAR_CAP; never blocks."""
    try:
        sizes = [(path, len(path.read_text(encoding="utf-8"))) for path in _edited_navmaps(hook_data)]
    except Exception as exc:
        logger.warning("[HOOKS] navmap: cap check failed (allowing): %s", exc)
        return _SILENT
    overs = [(path, size) for path, size in sizes if size > NAVMAP_CHAR_CAP]
    if not overs:
        return _SILENT
    text = " ".join(
        f"[NAVMAP] {path} is {size:,} chars, {size - NAVMAP_CHAR_CAP:,} over its {NAVMAP_CHAR_CAP:,} cap: "
        "injection cuts it near 10,000. Trim it in your next edit."
        for path, size in overs
    )
    logger.info("[HOOKS] navmap: over cap after edit: %s", text)
    result = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}, "systemMessage": text}
    return {"stdout": json.dumps(result), "exit_code": 0}
