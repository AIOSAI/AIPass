# =================== AIPass ====================
# Name: edit_gate.py
# Version: 1.1.0
# Description: Cross-branch and inbox write protection (PreToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-05-21
# Modified: 2026-08-04
# =============================================

"""Blocks unsafe edits: inbox writes, daemon confinement, cross-branch writes, diagnostics state."""

import importlib
import json
import os
from pathlib import Path
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger


STATE_FILE = Path(__file__).parent.parent.parent.parent.parent / ".diagnostics_state.json"
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
TRUSTED_CROSS_WRITERS: tuple[str, ...] = ("devpulse", "seedgo", "spawn")
_TRINITY_MEMORY_FILES = frozenset({"local.json", "observations.json"})
_NEWEST_FIRST_ARRAYS = ("sessions", "key_learnings")
_NUMBER_KEYS = ("number", "session_number")


def _entry_number(entry: dict) -> int | None:
    """Read an entry's ordinal, tolerating legacy schemas.

    Older .trinity files number sessions with 'session_number' rather than
    'number', and the rest of the fleet still honours it (@memory's rollover
    fixtures, @daemon's latest_session). A guard that reads only 'number' locks
    those branches out of their own memory with no way to comply.
    """
    for key in _NUMBER_KEYS:
        value = entry.get(key)
        if isinstance(value, int):
            return value
    return None


def _get_package_from_cwd(cwd: str) -> str:
    parts = Path(cwd).parts
    for i, part in enumerate(parts):
        if part == "src" and i + 2 < len(parts):
            return parts[i + 1]
    return ""


def _get_branch(file_path: str, package: str = "") -> str:
    parts = Path(file_path).parts
    if not package:
        return ""
    for i, part in enumerate(parts):
        if part == package and i > 0 and parts[i - 1] == "src" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def _resolve_after_text(tool_name: str, tool_input: dict, current_text: str) -> str | None:
    """Compute post-change file text for Edit/MultiEdit. Returns None on mismatch."""
    if tool_name == "Edit":
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        if old not in current_text:
            return None
        if tool_input.get("replace_all", False):
            return current_text.replace(old, new)
        return current_text.replace(old, new, 1)
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits", [])
        text = current_text
        for edit in edits:
            old = edit.get("old_string", "")
            new = edit.get("new_string", "")
            if old not in text:
                return None
            if edit.get("replace_all", False):
                text = text.replace(old, new)
            else:
                text = text.replace(old, new, 1)
        return text
    return None


def _evaluate_limits(before: dict, after: dict, limits: dict, el: Any) -> dict | None:
    """Diff changed entries and return block dict or None (allow)."""
    over = el.changed_entries(before, after, limits)
    if not over:
        return None
    if limits.get("enforce"):
        lines = ["Over-limit .trinity entries (shorten before saving):"]
        for v in over:
            lines.append(f"  {v['entry_type']} [{v['key']}]: {v['length']}/{v['cap']} chars (+{v['over_by']})")
        return {
            "stdout": json.dumps({"decision": "block", "reason": "\n".join(lines)}),
            "exit_code": 2,
            "sound": "edit gate",
        }
    for v in over:
        logger.warning(
            "[HOOKS] edit_gate: over-limit .trinity entry %s [%s]: %d/%d (+%d) — warn only",
            v["entry_type"],
            v["key"],
            v["length"],
            v["cap"],
            v["over_by"],
        )
    return None


def _todos_count_advisory(after: dict, branch: str) -> str:
    """Return advisory text if todos exceed rollover count limit, else empty string."""
    try:
        todos = after.get("todos")
        if not isinstance(todos, list):
            return ""
        cl = importlib.import_module("aipass.memory.apps.handlers.json.config_loader")
        cfg = cl.load()
        roll = cfg.get("rollover", {})
        branch_cfg = roll.get("per_branch", {}).get(branch) or roll.get("defaults", {})
        limit = branch_cfg.get("local", {}).get("todos", {}).get("count", 10)
        count = len(todos)
        if count <= limit:
            return ""
        msg = f"todos over limit ({count}/{limit}) — todos do not auto-roll; prune completed ones."
        logger.warning("[HOOKS] edit_gate: %s", msg)
        return msg
    except Exception as exc:
        logger.warning("[HOOKS] edit_gate: todos count check failed (skipping): %s", exc)
        return ""


def _check_section_counts(after: dict, branch: str, file_stem: str) -> None:
    """Warn (never block) when rolling sections exceed their configured entry-count cap."""
    try:
        cl = importlib.import_module("aipass.memory.apps.handlers.json.config_loader")
        roll = cl.section("rollover")
        branch_cfg = roll.get("per_branch", {}).get(branch) or roll.get("defaults", {})
        file_cfg = branch_cfg.get(file_stem, {})
        for section_name, section_cfg in file_cfg.items():
            if not isinstance(section_cfg, dict):
                continue
            cap = section_cfg.get("count")
            if cap is None:
                continue
            entries = after.get(section_name)
            if not isinstance(entries, list):
                continue
            count = len(entries)
            if count > cap:
                logger.warning(
                    "[HOOKS] edit_gate: %s.%s count over limit (%d/%d) — rollover will trim at next PreCompact",
                    file_stem,
                    section_name,
                    count,
                    cap,
                )
    except Exception as exc:
        logger.warning("[HOOKS] edit_gate: section count check failed (skipping): %s", exc)


def _check_newest_first(before: dict, after: dict) -> dict | None:
    """Reject sessions[]/key_learnings[] edits that add entries anywhere but index 0,
    or whose number doesn't exceed the max existing number (DPLAN-0278).

    These arrays are newest-first: rollover archives the TAIL as "oldest". A new
    entry appended after existing ones, or numbered <= the current max, gets
    silently archived as history on the next rollover instead of kept as recent.

    Ordinals are read through _entry_number, and an array where no entry carries a
    recognized ordinal skips the monotonicity check entirely — see the comment at
    that branch. The ordering check is schema-independent and always runs.
    """
    for key in _NEWEST_FIRST_ARRAYS:
        b = before.get(key)
        a = after.get(key)
        if not isinstance(b, list) or not isinstance(a, list) or len(a) <= len(b):
            continue

        added_count = len(a) - len(b)
        new_entries = a[:added_count]
        rest = a[added_count:]

        existing_numbers: list[int] = []
        for e in b:
            if not isinstance(e, dict):
                continue
            number = _entry_number(e)
            if number is not None:
                existing_numbers.append(number)
        max_existing = max(existing_numbers) if existing_numbers else 0

        if rest != b:
            reason = (
                f"{key} is newest-first — the entries after the new addition(s) no longer match the prior "
                "content, which means something was added after index 0 (e.g. appended at the tail). The "
                "next rollover archives the tail as 'oldest' and would silently drop a misplaced write. "
                "Insert new entries at index 0 only, leaving the rest of the array untouched."
            )
            return {
                "stdout": json.dumps({"decision": "block", "reason": reason}),
                "exit_code": 2,
                "sound": "edit gate",
            }

        new_numbers = [_entry_number(e) for e in new_entries if isinstance(e, dict)]

        # An unnumbered array is not a newest-first violation, it is a schema this
        # guard can't read. Blocking it would lock the branch out of its own memory
        # with no way to comply. The ordering check above still applies.
        if not existing_numbers and all(n is None for n in new_numbers):
            continue

        for entry in new_entries:
            if not isinstance(entry, dict):
                continue
            number = _entry_number(entry)
            if number is None:
                reason = (
                    f"{key}: new entry has no ordinal, but the existing entries are numbered "
                    f"(max {max_existing}). Number it with one of: {', '.join(_NUMBER_KEYS)} — "
                    "newest-first requires ascending numbers inserted at index 0."
                )
            elif number <= max_existing:
                reason = (
                    f"{key}: new entry number ({number}) must be greater than the max existing "
                    f"number ({max_existing}) — newest-first requires ascending numbers inserted at index 0."
                )
            else:
                continue
            return {
                "stdout": json.dumps({"decision": "block", "reason": reason}),
                "exit_code": 2,
                "sound": "edit gate",
            }
    return None


def _check_trinity_change(fp: Path, tool_name: str, tool_input: dict, branch: str) -> dict | None:
    """Check .trinity Write/Edit/MultiEdit for over-limit entries and newest-first violations."""
    try:
        resolved_path = str(fp.resolve()) if not fp.is_absolute() else str(fp)

        if tool_name == "Write":
            content = tool_input.get("content", "")
            after = json.loads(content)
            before = {}
            if Path(resolved_path).exists():
                before = json.loads(Path(resolved_path).read_text(encoding="utf-8"))
        else:
            if not Path(resolved_path).exists():
                return None
            current_text = Path(resolved_path).read_text(encoding="utf-8")
            before = json.loads(current_text)
            after_text = _resolve_after_text(tool_name, tool_input, current_text)
            if after_text is None:
                return None
            after = json.loads(after_text)

        block = _check_newest_first(before, after)
        if block:
            return block

        el = importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")
        limits = el.load_entry_limits(branch)
        if limits.get("enabled"):
            block = _evaluate_limits(before, after, limits, el)
            if block:
                return block

        _check_section_counts(after, branch, fp.stem)

        if fp.name == "local.json":
            advisory = _todos_count_advisory(after, branch)
            if advisory:
                return {"stdout": advisory, "exit_code": 0}

        return None
    except Exception as exc:
        logger.warning("[HOOKS] edit_gate: .trinity size check failed (allowing): %s", exc)
        return None


def handle(hook_data: dict) -> dict:
    """Apply edit security gates and return block or allow decision.

    Args:
        hook_data: Parsed hook event dict from engine.

    Returns:
        Result dict with stdout (block JSON or empty) and exit_code.
    """
    try:
        tool_name = hook_data.get("tool_name", "")
        tool_input = hook_data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")

        if tool_name not in EDIT_TOOLS:
            return {"stdout": "", "exit_code": 0}

        if not file_path:
            return {"stdout": "", "exit_code": 0}

        fp = Path(file_path)
        if fp.name == "inbox.json" and ".ai_mail.local" in fp.parts:
            reason = 'Direct writes to inbox.json are blocked.\nUse: drone @ai_mail email @<branch> "Subject" "Body"'
            return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": "edit gate"}

        cwd = hook_data.get("cwd", "") or os.getcwd()
        package = _get_package_from_cwd(cwd)
        cwd_branch = _get_branch(cwd, package)

        session_type = os.environ.get("AIPASS_SESSION_TYPE", "interactive")
        if session_type == "daemon" and cwd_branch:
            target_branch = _get_branch(str(fp.resolve()) if not fp.is_absolute() else str(fp), package)
            if target_branch and target_branch != cwd_branch:
                reason = (
                    f"Dispatched agent confined to own branch: '{cwd_branch}' "
                    f"cannot write to '{target_branch}' in daemon mode."
                )
                return {
                    "stdout": json.dumps({"decision": "block", "reason": reason}),
                    "exit_code": 2,
                    "sound": "edit gate",
                }
            repo_root = None
            for parent in Path(cwd).parents:
                if (parent / ".git").exists():
                    repo_root = parent
                    break
            if repo_root and not target_branch:
                allowed_prefix = str(repo_root / "src" / package / cwd_branch)
                resolved = str(fp.resolve()) if not fp.is_absolute() else str(fp)
                if not resolved.startswith(allowed_prefix):
                    reason = f"Dispatched agent restricted to {allowed_prefix}. Cannot write to: {file_path}"
                    return {
                        "stdout": json.dumps({"decision": "block", "reason": reason}),
                        "exit_code": 2,
                        "sound": "edit gate",
                    }

        target_branch = _get_branch(str(fp.resolve()) if not fp.is_absolute() else str(fp), package)

        if cwd_branch and target_branch and cwd_branch != target_branch:
            if cwd_branch not in TRUSTED_CROSS_WRITERS:
                reason = (
                    f"Cross-branch write blocked: '{cwd_branch}' cannot write to '{target_branch}'.\n"
                    f"Trusted cross-writers: {', '.join(TRUSTED_CROSS_WRITERS)}"
                )
                return {
                    "stdout": json.dumps({"decision": "block", "reason": reason}),
                    "exit_code": 2,
                    "sound": "edit gate",
                }

        trinity_tools = ("Write", "Edit", "MultiEdit")
        if tool_name in trinity_tools and fp.parent.name == ".trinity" and fp.name in _TRINITY_MEMORY_FILES:
            if target_branch:
                block = _check_trinity_change(fp, tool_name, tool_input, target_branch)
                if block:
                    return block

        if not file_path.endswith(".py"):
            return {"stdout": "", "exit_code": 0}

        if not STATE_FILE.exists():
            return {"stdout": "", "exit_code": 0}

        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as exc:
            logger.info("[HOOKS] edit_gate: diagnostics_state unreadable: %s", exc)
            return {"stdout": "", "exit_code": 0}

        errored_file = state.get("file", "")
        errors = state.get("errors", [])

        if not errors:
            return {"stdout": "", "exit_code": 0}

        try:
            current = str(Path(file_path).resolve())
            errored = str(Path(errored_file).resolve())
        except (OSError, ValueError) as exc:
            logger.info("[HOOKS] edit_gate: path resolution failed: %s", exc)
            return {"stdout": "", "exit_code": 0}

        if current == errored:
            return {"stdout": "", "exit_code": 0}

        current_branch = _get_branch(current, package)
        errored_branch = _get_branch(errored, package)
        if not errored_branch:
            return {"stdout": "", "exit_code": 0}
        if current_branch and errored_branch and current_branch != errored_branch:
            return {"stdout": "", "exit_code": 0}

        error_summary = "\n".join(f"  L{e['line']}: {e['message']}" for e in errors[:5])
        reason = f"Fix {len(errors)} error(s) in {Path(errored_file).name} before editing other files:\n{error_summary}"
        return {
            "stdout": json.dumps({"decision": "block", "reason": reason}),
            "exit_code": 2,
            "sound": "edit gate",
        }

    except Exception as exc:
        logger.info("[HOOKS] edit_gate: unexpected error (allowing): %s", exc)
        return {"stdout": "", "exit_code": 0}
