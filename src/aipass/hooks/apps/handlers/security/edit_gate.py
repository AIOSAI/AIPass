# =================== AIPass ====================
# Name: edit_gate.py
# Version: 1.20.0
# Description: Cross-project and who-owns-it (tool + scripted, modules/write_ownership), inbox and
#              shell-to-memory write protection (PreToolUse), plus the shell-memory tripwire
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-05-21
# Modified: 2026-10-17
# =============================================

"""Blocks unsafe edits: inbox, cross-project, cross-branch and shell-to-memory writes, daemon confinement, diagnostics
state. Reports a shell memory write the reader could not see, after the call.

Failure mode: handle() refuses the call it was checking when it crashes; the tripwire pair report and never block,
so a crash there leaves one call unwatched, logged. The engine refuses on import error and timeout for all three."""

import importlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger


EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
GATE_CRASHED = (
    "edit_gate could not check this call ({error}), so it is refused: a gate that cannot read a call "
    "does not let it through.\n"
    'Mail @hooks and @devpulse: drone @ai_mail email @hooks "Gate broken: edit_gate" "<what you ran, and this text>"'
)
# Named for the log line only: WHO is decided by modules/admin_seat's verified rail. Spelled, not imported:
# a handler reaches modules at call time. It must equal modules/admin_seat.ADMIN_SEAT; no test pins that.
ADMIN_SEAT = "devpulse"
# @spawn owns passport's schema, so it is measured by SIZE only (@memory's check_file_budget).
_TRINITY_MEMORY_FILES = frozenset({"local.json", "observations.json", "passport.json"})
_FILE_BUDGET_FILES = frozenset({"passport.json"})
# src/<pkg>/<branch>/.trinity is four deep; bounded, as a full repo walk on every Bash call costs too much.
_TRINITY_SCAN_DEPTH = 4
_NEWEST_FIRST_ARRAYS = ("sessions", "key_learnings")
_NUMBER_KEYS = ("number", "session_number")
# Over the pad count is legal on disk; the oldest roll to @memory's backlog file (todo_roll.backlog_path_for).
_TODOS_COUNT_FALLBACK = 10
_TODO_BACKLOG = ".backup/todo/{branch}/backlog.json"
# Pending snapshots keyed by tool_use_id and capped: a call whose PostToolUse never fires must not grow it.
_TRIPWIRE_DIR = Path(tempfile.gettempdir())
_TRIPWIRE_PENDING_MAX = 8
# The log line is the diagnostic, not the copy: the head names the rule and the target.
_REFUSAL_LOG_CHARS = 500
# The sanctioned writers of memory files from a shell: drone verbs, not raw writes.
_MEMORY_VERB_TARGETS = frozenset({"@memory", "@spawn"})
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")


def _entry_number(entry: dict) -> int | None:
    """Read an entry's ordinal, tolerating legacy schemas.

    Older .trinity files use 'session_number'; reading only 'number' locks those branches out of their memory."""
    for key in _NUMBER_KEYS:
        value = entry.get(key)
        if isinstance(value, int):
            return value
    return None


def _import_module(name: str) -> Any:
    """Import a module this gate reads at call time.

    A seam for the tests: they replace it by name instead of patching importlib.import_module process-wide."""
    return importlib.import_module(name)


def _ownership() -> Any:
    """modules/write_ownership, reached at call time: a handler never imports a module at import time."""
    return _import_module("aipass.hooks.apps.modules.write_ownership")


def _refuse(reason: str) -> dict:
    """Build the one refusal shape every gate in this file returns — and write the line that says why.

    engine.jsonl never records the reason, so this line is the only record of what was refused.
    Paths with extra detail log their own line first; two lines there is intended."""
    logger.warning("[HOOKS] edit_gate: refused — %s", _one_line(reason))
    return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": "edit gate"}


def _one_line(reason: str, cap: int = _REFUSAL_LOG_CHARS) -> str:
    """Flatten a refusal to one bounded log line: the head is what names the rule and the target."""
    flat = " | ".join(part.strip() for part in reason.splitlines() if part.strip())
    return flat if len(flat) <= cap else f"{flat[:cap]}… (+{len(flat) - cap} chars, full text in the refusal)"


def _is_admin_seat(cwd: str) -> bool:
    """True only when the 5-leg admin grant verifies for this session.

    Delegates to ``modules/admin_seat.is_admin_seat``: a security exemption has one reading, never two."""
    try:
        admin = _import_module("aipass.hooks.apps.modules.admin_seat")
    except Exception as exc:
        # A missing module must never open the exemption.
        logger.warning("[HOOKS] edit_gate: admin lane dark — admin_seat unavailable: %s", exc)
        return False
    return bool(admin.is_admin_seat(cwd))


def _check_project_boundary(cwd: str, caller: Any, landing: Any, target: Path) -> dict | None:
    """Block a write that crosses out of the caller's project, in any direction.

    Only the verified admin seat crosses. *caller* and *landing* are write_ownership Projects."""
    if not _ownership().is_crossing(caller, landing):
        return None
    if _is_admin_seat(cwd):
        logger.info(
            "[HOOKS] edit_gate: cross-project write ALLOWED for the admin seat (@%s): %s -> %s (%s)",
            ADMIN_SEAT,
            caller.root.name,
            landing.root.name,
            target,
        )
        return None

    logger.warning(
        "[HOOKS] edit_gate: cross-project write refused: caller root %s != target root %s (%s)",
        caller.root,
        landing.root,
        target,
    )
    return _cross_project_block(caller.root, landing.root, target, "")


def _cross_project_block(caller_root: Path, target_root: Path, target: Path, how: str) -> dict:
    """Build the refusal both lanes print. *how* names the shell verb, or "" for a tool edit."""
    lane = f"Cross-project write blocked ({how})" if how else "Cross-project write blocked"
    reason = (
        f"{lane}: project '{caller_root.name}' cannot write into project '{target_root.name}'.\n"
        f"Target: {target}\n"
        "A project writes inside itself only — never into its host, a sibling or a project it holds. This is the "
        "file-layer twin of the mail fence that refuses cross-project sends.\n"
        'To reach that project: drone @devpulse feedback send "Subject" "Body"'
    )
    return _refuse(reason)


def _bash_write_targets(cwd: str, command: str) -> list[tuple[Path, str]]:
    """Every (path, how) the shell reader can see *command* write, read once for both Bash-lane rules.

    A parser that cannot read a command raises, so the gate's crash refusal refuses the call."""
    if not command:
        return []
    targets = _import_module("aipass.hooks.apps.modules.bash_writes").write_targets(command, cwd)
    # Default-deny: every operand of a program that does not only read is judged by the same rules.
    invocations = _import_module("aipass.hooks.apps.modules.shell_reader").invocations(command, cwd)
    places = _import_module("aipass.hooks.apps.modules.write_ownership").in_a_branch  # a flag value is no write
    operands = _import_module("aipass.hooks.apps.modules.shell_programs").named_operands(invocations, places)
    return targets + [(path, f"{program} (not a read-only program)") for program, path in operands]


def _check_bash_project_boundary(cwd: str, caller: Any, targets: list[tuple[Path, str]]) -> dict | None:
    """Block a cross-project write made through the shell rather than a tool.

    ``bash_writes`` reports only what it can SEE (``bash_writes.NOT_CAUGHT``); a guessing parser would
    refuse correct commands. A target that cannot be probed on disk is refused first."""
    wo = _ownership()
    if unprobeable := wo.unprobeable(targets):
        return _refuse(unprobeable)
    if caller is None:
        return None
    for target, how in targets:
        landing = wo.project_of(target)
        if not wo.is_crossing(caller, landing):
            continue
        if _is_admin_seat(cwd):
            logger.info(
                "[HOOKS] edit_gate: scripted cross-project write ALLOWED for the admin seat (@%s): %s -> %s (%s)",
                ADMIN_SEAT,
                caller.root.name,
                landing.root.name,
                target,
            )
            return None
        logger.warning(
            "[HOOKS] edit_gate: scripted cross-project write refused: %s -> %s via %s (%s)",
            caller.root,
            landing.root,
            how,
            target,
        )
        return _cross_project_block(caller.root, landing.root, target, how)
    return None


def _check_bash_ownership(cwd: str, caller: Any, targets: list[tuple[Path, str]]) -> dict | None:
    """Refuse a shell write into a file this seat does not own, inside its own project.

    Convicts on write grammar only: an interpreter's held paths are left to the project fence."""
    wo = _ownership()
    for target, how in targets:
        reason = wo.ownership_refusal(caller, wo.project_of(target), cwd, target, how)
        if reason:
            logger.warning("[HOOKS] edit_gate: scripted write refused, not the seat's: %s via %s", target, how)
            return _refuse(reason)
    return None


def _check_bash_memory_write(targets: list[tuple[Path, str]]) -> dict | None:
    """Refuse a shell write to a .trinity memory file: every seat, every project, admin included.

    The admin exemption is not consulted: it reaches another project, it says nothing about memory.
    An interpreter that only READS a memory path is refused too; the refusal names that over-refusal."""
    for target, how in targets:
        if target.parent.name != ".trinity" or target.name not in _TRINITY_MEMORY_FILES:
            continue
        logger.warning("[HOOKS] edit_gate: shell write to a memory file refused: %s via %s", target, how)
        reason = (
            f"Memory files are not written from a shell: {target} via {how}.\n"
            f"{_where_memory_is_written()}\n"
            "Only reading it? An interpreter that names a memory path is refused whether it reads or writes, "
            "because this gate cannot tell which. Read the file with the Read tool, cat or jq."
        )
        return _refuse(reason)
    return None


def _memory_service_reachable() -> bool:
    """True when @memory's cap module imports from where this hook is running.

    Asked at refusal time, not at import: `aipass init` projects have no @memory."""
    try:
        _import_module("aipass.memory.apps.modules.door_entry_limits")
        return True
    except Exception as exc:  # any import failure means "not reachable here"
        logger.info("[HOOKS] edit_gate: @memory is not reachable from this project (%s)", exc)
        return False


def _where_memory_is_written() -> str:
    """The shell refusal's cure sentence; outside the fleet there is no cap and no ``drone @memory`` verb."""
    files = ", ".join(sorted(_TRINITY_MEMORY_FILES))
    if _memory_service_reachable():
        return (
            f"Write {files} with the Edit or Write tool, where @memory's caps are measured, or through a "
            "drone @memory verb. A shell write lands unmeasured, which is how whole branches drifted over cap."
        )
    return (
        f"Write {files} with the Edit or Write tool. This project has no @memory service, so no cap is "
        "measured here either way; the rule stands because a shell write is invisible to every reader that "
        "would measure one."
    )


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


def _entries_of(container: Any, kind: str) -> list[tuple[str, Any]]:
    """Normalise a list- or dict-shaped container to (key, entry) pairs."""
    if kind == "list" and isinstance(container, list):
        return [(str(i), item) for i, item in enumerate(container)]
    if kind == "dict" and isinstance(container, dict):
        return [(str(k), v) for k, v in container.items()]
    return []


def _log_carried(entry_type: str, container: str, key: str, field: str) -> None:
    """Record a drifted entry this write carried but did not author.

    Not refused, not printed: detection belongs to ``drone @memory lint``. INFO: carrying is not misbehaviour."""
    logger.info(
        "[HOOKS] edit_gate: CARRIED (not authored, not refused) %s [%s] in %s — no '%s' field. "
        "Cure it with drone @memory lint.",
        entry_type,
        key,
        container,
        field,
    )


def _missing_field_violations(before: dict, after: dict, limits: dict) -> list[dict]:
    """Refuse entries whose CANONICAL field is absent (DPLAN-0318 bug B3).

    A write is refused for what it AUTHORS, never for what it CARRIES: refusing carried drift deadlocks the
    rollover shrinking the file. Identity is the raw entry, never the index: a prepend shifts every position."""
    hits: list[dict] = []
    for type_name, type_def in limits.get("entry_types", {}).items():
        if not isinstance(type_def, dict):
            continue
        container_key = type_def.get("container", "")
        kind = type_def.get("kind", "dict")
        field = type_def.get("field", "value")

        after_container = after.get(container_key)
        if after_container is None:
            continue

        carried = [entry for _, entry in _entries_of(before.get(container_key), kind)]

        for key, entry in _entries_of(after_container, kind):
            # Plain-string entries carry their own text; @memory's extractor measures them.
            if not isinstance(entry, dict) or field in entry:
                continue
            if entry in carried:
                # Byte-identical to disk, so not authored here; refusing it deadlocks the rollover.
                _log_carried(type_name, container_key, key, field)
                continue
            hits.append(
                {
                    "entry_type": type_name,
                    "container": container_key,
                    "key": key,
                    "length": 0,
                    "cap": type_def.get("max_chars", 0),
                    "over_by": 0,
                    "reason": "missing_field",
                    "found_type": "missing",
                    "field": field,
                }
            )
    return hits


def _entry_text(v: dict, after: dict, limits: dict) -> str | None:
    """The authored text behind an over-cap record, read back out of the proposed file.

    Anything not resolving to a string of exactly the recorded length answers None: no cut on unmeasured text."""
    type_def = limits.get("entry_types", {}).get(v.get("entry_type", ""))
    if not isinstance(type_def, dict):
        return None
    container = after.get(type_def.get("container", ""))
    key = str(v.get("key", ""))
    if isinstance(container, list):
        entry = container[int(key)] if key.isdigit() and int(key) < len(container) else None
    elif isinstance(container, dict):
        entry = container.get(key)
    else:
        return None
    if isinstance(entry, dict):
        entry = entry.get(type_def.get("field", "value"))
    if not isinstance(entry, str) or len(entry) != v.get("length"):
        logger.info("[HOOKS] edit_gate: no cut point for %s [%s] — text did not resolve", v.get("entry_type"), key)
        return None
    return entry


def _cut_point(text: str, cap: int) -> str:
    """Where the cap fell: the kept prefix, a bar, and the overflow past it (DPLAN-0342).

    Both halves are JSON-quoted so boundary whitespace shows; ``len`` slices in code points, the cap's unit."""
    kept = json.dumps(text[:cap], ensure_ascii=False)
    over = json.dumps(text[cap:], ensure_ascii=False)
    return f"kept: {kept} | over: {over}"


def _where(v: dict) -> str:
    """'sessions [0]' for an entry, just the file name for a whole-file finding."""
    if v.get("key") in (None, "", v.get("entry_type")):
        return str(v.get("entry_type", "?"))
    return f"{v['entry_type']} [{v['key']}]"


def _format_violation(v: dict, text: str | None = None, allowed: list[str] | None = None) -> str:
    """Render one violation line, plus the cut point when the text is known.

    Non-over-cap species carry zeros (@memory's six-key contract) and must not render as "0/300 chars (+0)"."""
    reason = v.get("reason")
    if reason == "unknown_field":
        shape = ", ".join(allowed) if allowed else "the published shape"
        return (
            f"  {_where(v)}: field '{v.get('field', '?')}' is not part of the entry shape — "
            f"allowed: {shape}. Remove it, or ask @memory to add it to the shape."
        )
    if reason == "field_over_cap":
        units = v.get("units", "chars")
        return f"  {_where(v)}: '{v.get('field', '?')}' is {v['length']}/{v['cap']} {units} (+{v['over_by']} over)"
    if reason == "file_over_budget":
        return (
            f"  {_where(v)}: the whole file is {v['length']}/{v['cap']} chars (+{v['over_by']} over). "
            "Roll or trim before saving — this budget is @memory's, read here, never copied."
        )
    if reason == "missing_field":
        return (
            f"  {v['entry_type']} [{v['key']}]: no '{v.get('field', '?')}' field — "
            f"cannot be measured against its {v['cap']}-char cap. "
            f"Rename the field to '{v.get('field', '?')}' (the canonical name)."
        )
    if reason:
        return (
            f"  {v['entry_type']} [{v['key']}]: unmeasurable — expected a string, "
            f"found {v.get('found_type', 'unknown')}. Cap is {v['cap']} chars."
        )
    line = f"  {v['entry_type']} [{v['key']}]: {v['length']}/{v['cap']} chars (+{v['over_by']})"
    if text is None:
        return line
    return f"{line}\n    {_cut_point(text, v['cap'])}"


def _log_violation(v: dict, text: str | None = None) -> None:
    """Warn-mode log line — carries the same cause, and cut, the block would have named."""
    reason = v.get("reason")
    if reason in ("unknown_field", "field_over_cap", "file_over_budget"):
        logger.warning(
            "[HOOKS] edit_gate: %s .trinity %s field '%s' %d/%d %s (+%d) — warn only",
            reason,
            _where(v),
            v.get("field", "?"),
            v["length"],
            v["cap"],
            v.get("units", "chars"),
            v["over_by"],
        )
        return
    if reason:
        logger.warning(
            "[HOOKS] edit_gate: unreadable .trinity entry %s [%s]: %s (field '%s', cap %d) — warn only",
            v["entry_type"],
            v["key"],
            v["reason"],
            v.get("field", v.get("found_type", "?")),
            v["cap"],
        )
        return
    logger.warning(
        "[HOOKS] edit_gate: over-limit .trinity entry %s [%s]: %d/%d (+%d)%s — warn only",
        v["entry_type"],
        v["key"],
        v["length"],
        v["cap"],
        v["over_by"],
        "" if text is None else f" {_cut_point(text, v['cap'])}",
    )


def _dedupe_violations(violations: list[dict]) -> list[dict]:
    """Collapse violations naming the same entry, first record wins.

    The overlap with @memory's extractor is deliberate; the container is keyed because two types index "0"."""
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict] = []
    for v in violations:
        ident = (v.get("entry_type", ""), v.get("container", ""), v.get("key", ""))
        if ident in seen:
            continue
        seen.add(ident)
        unique.append(v)
    return unique


def _allowed_fields(v: dict, limits: dict, el: Any) -> list[str] | None:
    """The entry type's published field names, for an unknown-field refusal.

    Read through ``fields_for``: the shape is memory's to publish; an unconfigured type answers {}."""
    if v.get("reason") != "unknown_field":
        return None
    try:
        fields = el.fields_for(v.get("entry_type", ""), limits)
    except AttributeError as exc:
        # An older @memory has no fields_for; the refusal stays correct without the allow-list.
        logger.info("[HOOKS] edit_gate: fields_for unavailable, refusal renders without the shape: %s", exc)
        return None
    # Declaration order, not alphabetical: the config's order reads as the entry's shape.
    return list(fields) if isinstance(fields, dict) and fields else None


def _evaluate_limits(before: dict, after: dict, limits: dict, el: Any) -> dict | None:
    """Diff changed entries and return block dict or None (allow)."""
    over = el.changed_entries(before, after, limits)
    over = _dedupe_violations(over + _missing_field_violations(before, after, limits))
    if not over:
        return None
    texts = [None if v.get("reason") else _entry_text(v, after, limits) for v in over]
    if limits.get("enforce"):
        lines = ["Unwritable .trinity entries (fix before saving):"]
        for v, text in zip(over, texts, strict=True):
            lines.append(_format_violation(v, text, _allowed_fields(v, limits, el)))
        # A shell write the reader sees is refused (_check_bash_memory_write); one it cannot see, tripwire() reports.
        lines.append(
            "  (Caps are measured on Edit/Write; a write to a memory file made through Bash is refused. "
            "Cure drift already on disk with drone @memory lint.)"
        )
        return _refuse("\n".join(lines))
    for v, text in zip(over, texts, strict=True):
        _log_violation(v, text)
    return None


def _evaluate_file_budget(file_name: str, after_text: str, limits: dict, el: Any) -> dict | None:
    """Measure a whole-file budget — the passport row (DPLAN-0347, @memory 1.11.0).

    SIZE only: @spawn owns passport's schema, @memory the numbers. Warn mode logs and allows."""
    if file_name not in _FILE_BUDGET_FILES:
        return None
    try:
        violations = el.check_file_budget(file_name, after_text)
    except AttributeError as exc:
        # An older @memory publishes no file budgets: a size rule that cannot be read has not failed.
        logger.info("[HOOKS] edit_gate: check_file_budget unavailable, %s unmeasured: %s", file_name, exc)
        return None
    if not violations:
        return None
    if not limits.get("enforce"):
        for v in violations:
            _log_violation(v)
        return None
    lines = [f"{file_name} is over its budget (fix before saving):"]
    lines.extend(_format_violation(v) for v in violations)
    lines.append(
        "  The identity block renders from this file on every cadence beat, so its size is a standing cost. "
        "Caps live in @memory's memory.config.json (file_budgets); @spawn owns the schema."
    )
    logger.warning("[HOOKS] edit_gate: %s refused — %d file-budget violation(s)", file_name, len(violations))
    return _refuse("\n".join(lines))


def _todos_count_advisory(after: dict, branch: str) -> str:
    """Return advisory text if todos exceed rollover count limit, else empty string.

    Throttled: over the cap is a STANDING condition and a per-edit line trips @trigger's repeat escalation,
    so the log line throttles with the stdout line. The count is @memory's config_loader.get_todos_count."""
    try:
        todos = after.get("todos")
        if not isinstance(todos, list):
            return ""
        cl = _import_module("aipass.memory.apps.modules.door_config_loader")
        configured = cl.get_todos_count(branch)
        limit = configured if configured is not None else _TODOS_COUNT_FALLBACK
        count = len(todos)
        if count <= limit:
            return ""
        if configured is None:
            msg = (
                f"todos over limit ({count}/{limit}) — no usable todos count in @memory's config "
                "(rollover.defaults.local.todos.count), so nothing rolls; delete done ones by hand."
            )
        else:
            msg = (
                f"todos over limit ({count}/{limit}) — legal on disk; the oldest {count - limit} roll off at the "
                f"next rollover (PreCompact, or drone @memory rollover run --branch @{branch}) to "
                f"{_TODO_BACKLOG.format(branch=branch)}; drone @memory todo backlog @{branch} reads it."
            )
        cadence = _import_module("aipass.hooks.apps.modules.cadence")
        if not cadence.should_fire_advisory("todos_count"):
            # debug: the condition is unchanged and already recorded by the emission that fired.
            logger.debug("[HOOKS] edit_gate: %s (throttled)", msg)
            return ""
        logger.warning("[HOOKS] edit_gate: %s", msg)
        return msg
    except Exception as exc:
        logger.warning("[HOOKS] edit_gate: todos count check failed (skipping): %s", exc)
        return ""


def _is_auto_compact(entry: Any) -> bool:
    """True for auto-compact snapshot entries.

    Must match rollover/extractor.py exactly, or the warning becomes unsatisfiable."""
    return isinstance(entry, dict) and entry.get("status") == "auto-compact"


def _note_over_budget(branch: str, file_stem: str, label: str, count: int, cap: int) -> None:
    """Log one operator-facing line for a section over its rollover budget.

    INFO, not WARNING: over-budget is chosen behaviour; as a WARNING it fed @trigger's escalation lane."""
    logger.info(
        "[HOOKS] edit_gate: @%s .trinity/%s.json — %s has %d entries, %d over the rollover budget of %d. "
        "The @memory rollover hook archives the %d oldest at the next PreCompact; "
        "nothing is lost — recall them with drone @memory search.",
        branch,
        file_stem,
        label,
        count,
        count - cap,
        cap,
        count - cap,
    )


def _note_todos_over_pad(branch: str, count: int, cap: int) -> None:
    """The todos twin of _note_over_budget: the roll is real, its destination is a file.

    Todos roll to the backlog file, never to vectors, so "drone @memory search" would be the false clause."""
    logger.info(
        "[HOOKS] edit_gate: @%s .trinity/local.json — todos has %d entries, %d over the pad of %d. "
        "The %d oldest roll to %s at @%s's next PreCompact (or drone @memory rollover run --branch @%s); "
        "nothing is lost — drone @memory todo backlog @%s lists them.",
        branch,
        count,
        count - cap,
        cap,
        count - cap,
        _TODO_BACKLOG.format(branch=branch),
        branch,
        branch,
        branch,
    )


def _check_session_counts(branch: str, file_stem: str, entries: list, section_cfg: dict) -> None:
    """Warn on the sessions section, budgeting auto-compact snapshots separately.

    Snapshots carry their own cap in the extractor; counting them against the regular cap is unsatisfiable."""
    auto_cap = section_cfg.get("auto_compact_cap")
    if auto_cap is not None:
        snapshots = [e for e in entries if _is_auto_compact(e)]
        if len(snapshots) > auto_cap:
            _note_over_budget(branch, file_stem, "sessions (auto-compact snapshots)", len(snapshots), auto_cap)

    cap = section_cfg.get("count")
    if cap is not None:
        # Unconditional split, matching the extractor whether or not auto_compact_cap is configured.
        regular = [e for e in entries if not _is_auto_compact(e)]
        if len(regular) > cap:
            _note_over_budget(branch, file_stem, "sessions", len(regular), cap)


def _check_section_counts(after: dict, branch: str, file_stem: str) -> None:
    """Warn (never block) when rolling sections exceed their configured entry-count cap."""
    try:
        cl = _import_module("aipass.memory.apps.modules.door_config_loader")
        roll = cl.section("rollover")
        branch_cfg = roll.get("per_branch", {}).get(branch) or roll.get("defaults", {})
        file_cfg = branch_cfg.get(file_stem, {})
        for section_name, section_cfg in file_cfg.items():
            if not isinstance(section_cfg, dict):
                continue
            entries = after.get(section_name)
            if not isinstance(entries, list):
                continue

            if section_name == "sessions":
                _check_session_counts(branch, file_stem, entries, section_cfg)
                continue

            cap = section_cfg.get("count")
            if cap is None or len(entries) <= cap:
                continue
            if section_name == "todos":
                _note_todos_over_pad(branch, len(entries), cap)
            else:
                _note_over_budget(branch, file_stem, section_name, len(entries), cap)
    except Exception as exc:
        logger.warning("[HOOKS] edit_gate: section count check failed (skipping): %s", exc)


def _check_newest_first(before: dict, after: dict) -> dict | None:
    """Reject sessions[]/key_learnings[] edits that add entries anywhere but index 0,
    or whose number doesn't exceed the max existing number.

    Newest-first: rollover archives the TAIL as oldest, so a misplaced or low-numbered entry is lost."""
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
            return _refuse(reason)

        new_numbers = [_entry_number(e) for e in new_entries if isinstance(e, dict)]

        # An unnumbered array is a schema this guard can't read; blocking it locks the branch out of its memory.
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
            return _refuse(reason)
    return None


def _unparseable_refusal(fp: Path, exc: ValueError) -> dict:
    """Refuse a memory write whose RESULT does not parse — the file would be broken for every reader.

    Every writer is atomic, so refusing the edit means the file never breaks (docs/trinity_memory_gate.md)."""
    reason = (
        f"{fp.name}: this edit would leave the file unparseable as JSON ({exc}). A memory file that does "
        "not parse is broken for every reader until the next edit lands — @memory, this gate, the tripwire "
        "and the startup read all see a corrupt seat. Make the edit so the whole file still parses, then retry."
    )
    return _refuse(reason)


def _check_trinity_change(fp: Path, tool_name: str, tool_input: dict, branch: str) -> dict | None:
    """Check .trinity Write/Edit/MultiEdit for unparseable results, over-limit entries and newest-first violations."""
    try:
        resolved_path = str(fp.resolve()) if not fp.is_absolute() else str(fp)

        if tool_name == "Write":
            after_text = tool_input.get("content", "")
            current_text = None
            if Path(resolved_path).exists():
                current_text = Path(resolved_path).read_text(encoding="utf-8")
        else:
            if not Path(resolved_path).exists():
                return None
            current_text = Path(resolved_path).read_text(encoding="utf-8")
            resolved_after = _resolve_after_text(tool_name, tool_input, current_text)
            if resolved_after is None:
                return None
            after_text = resolved_after

        try:
            after = json.loads(after_text)
        except ValueError as exc:
            logger.info("[HOOKS] edit_gate: refused a %s that leaves %s unparseable: %s", tool_name, fp, exc)
            return _unparseable_refusal(fp, exc)

        try:
            before = json.loads(current_text) if current_text is not None else {}
        except ValueError as exc:
            # Already broken on disk and this edit parses: it is the repair, judged as a new file.
            logger.warning(
                "[HOOKS] edit_gate: %s did not parse before this %s, which repairs it: %s", fp, tool_name, exc
            )
            before = {}

        block = _check_newest_first(before, after)
        if block:
            return block

        el = _import_module("aipass.memory.apps.modules.door_entry_limits")
        limits = el.load_entry_limits(branch)
        if limits.get("enabled"):
            block = _evaluate_limits(before, after, limits, el)
            if block:
                return block
            block = _evaluate_file_budget(fp.name, after_text, limits, el)
            if block:
                return block

        _check_section_counts(after, branch, fp.stem)

        if fp.name == "local.json":
            advisory = _todos_count_advisory(after, branch)
            if advisory:
                # Context, not plain stdout: on PreToolUse exit 0 plain stdout never reaches the model.
                output = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": advisory}}
                return {"stdout": json.dumps(output), "exit_code": 0}

        return None
    except Exception as exc:  # fail closed: an unreadable memory file must not pass every cap
        logger.warning("[HOOKS] edit_gate: .trinity check could not run, refusing: %s", exc)
        return _refuse(
            f"{fp.name} could not be checked against its caps ({type(exc).__name__}: {exc}), so the write is "
            "refused: a memory file the gate cannot read is not one it has measured. Make it readable, then retry."
        )


def _seat_trinity(cwd: str) -> Path | None:
    """The nearest .trinity directory at or above the session's cwd: the seat's own memory."""
    try:
        start = Path(cwd).resolve()
    except (OSError, ValueError) as exc:
        logger.info("[HOOKS] edit_gate tripwire: cwd unresolvable %r: %s", cwd, exc)
        return None
    for candidate in (start, *start.parents):
        if (candidate / ".trinity").is_dir():
            return candidate / ".trinity"
    return None


def _watched_trinity_dirs(cwd: str) -> list[Path]:
    """Every .trinity in the project, the seat's own first; just the seat's when there is no project.

    A stat is all it takes to notice; no file is read unless something changed."""
    seat = _seat_trinity(cwd)
    dirs: list[Path] = [seat] if seat is not None else []
    project = _ownership().project_of(Path(cwd)) if cwd else None
    if project is None:
        return dirs
    root = project.root
    try:
        for depth in range(1, _TRINITY_SCAN_DEPTH + 1):
            pattern = "/".join(["*"] * (depth - 1) + [".trinity"])
            for found in root.glob(pattern):
                if found.is_dir() and found not in dirs:
                    dirs.append(found)
    except OSError as exc:
        logger.info("[HOOKS] edit_gate tripwire: .trinity scan under %s failed: %s", root, exc)
    return dirs


def _memory_stats(dirs: list[Path]) -> dict[str, list[int] | None]:
    """(mtime_ns, size) per watched file, keyed by full path.

    None for a missing file, so creation or removal reads as a change; keyed by path, as branches share names."""
    stats: dict[str, list[int] | None] = {}
    for trinity in dirs:
        for name in sorted(_TRINITY_MEMORY_FILES):
            path = trinity / name
            if not path.is_file():
                stats[str(path)] = None
                continue
            found = path.stat()
            stats[str(path)] = [found.st_mtime_ns, found.st_size]
    return stats


def _tripwire_path(hook_data: dict) -> Path:
    return _TRIPWIRE_DIR / f"aipass-trinity-tripwire-{hook_data.get('session_id') or 'nosession'}.json"


def _read_pending(path: Path) -> dict:
    """The session's pending snapshots, keyed by tool_use_id. An unreadable file starts fresh and says so."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.info("[HOOKS] edit_gate tripwire: unreadable snapshot file %s, starting fresh: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _runs_memory_verb(command: str, cwd: str) -> bool:
    """True when some segment of *command* is a drone @memory or @spawn verb, the sanctioned writers."""
    bw = _import_module("aipass.hooks.apps.modules.bash_writes")
    for segment, _hits in bw.write_targets_by_segment(command, cwd):
        words = list(segment)
        while words and _ENV_ASSIGNMENT.match(words[0]):
            words.pop(0)
        if len(words) > 1 and Path(words[0]).name == "drone" and words[1] in _MEMORY_VERB_TARGETS:
            return True
    return False


def _measure_memory_file(path: Path) -> list[str]:
    """What a memory file holds that fails its caps, rendered as the Edit refusal renders it, cut point included.

    The WHOLE file is measured (the snapshot holds stats, not text), so the report says "holds", never "wrote"."""
    if not path.is_file():
        return [f"  {path.name} no longer exists."]
    if path.name in _FILE_BUDGET_FILES:
        el = _import_module("aipass.memory.apps.modules.door_entry_limits")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.info("[HOOKS] edit_gate tripwire: %s unreadable after a shell call: %s", path, exc)
            return [f"  {path.name} could not be read: {exc}"]
        return [_format_violation(v) for v in el.check_file_budget(path.name, text)]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.info("[HOOKS] edit_gate tripwire: %s unreadable after a shell call: %s", path, exc)
        return [f"  {path.name} no longer parses as JSON: {exc}"]
    if not isinstance(doc, dict):
        return [f"  {path.name} is no longer a JSON object."]
    el = _import_module("aipass.memory.apps.modules.door_entry_limits")
    limits = el.load_entry_limits(path.parent.parent.name)
    if not limits.get("enabled"):
        return []
    over = _dedupe_violations(el.changed_entries({}, doc, limits))
    return [_format_violation(v, None if v.get("reason") else _entry_text(v, doc, limits)) for v in over]


def handle(hook_data: dict) -> dict:
    """Apply edit security gates and return block or allow decision."""
    tool_name = hook_data.get("tool_name", "") if isinstance(hook_data, dict) else ""
    try:
        tool_input = hook_data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")

        # The scripted lane: project fence, memory rule, ownership. Inbox and daemon checks need a named file;
        # what the reader cannot see (bash_writes.NOT_CAUGHT) the tripwire reports after the call.
        if tool_name == "Bash":
            cwd = hook_data.get("cwd", "") or os.getcwd()
            targets = _bash_write_targets(cwd, tool_input.get("command", ""))
            if not targets:
                return {"stdout": "", "exit_code": 0}
            caller = _ownership().project_of(Path(cwd))
            return (
                _check_bash_project_boundary(cwd, caller, targets)
                or _check_bash_memory_write(targets)
                or _check_bash_ownership(cwd, caller, targets)
                or {"stdout": "", "exit_code": 0}
            )

        if tool_name not in EDIT_TOOLS:
            return {"stdout": "", "exit_code": 0}

        if not file_path:
            return {"stdout": "", "exit_code": 0}

        fp = Path(file_path)
        if fp.name == "inbox.json" and ".ai_mail.local" in fp.parts:
            reason = 'Direct writes to inbox.json are blocked.\nUse: drone @ai_mail email @<branch> "Subject" "Body"'
            return _refuse(reason)

        cwd = hook_data.get("cwd", "") or os.getcwd()

        # Outermost boundary first, then daemon confinement, then whose file it is.
        wo = _ownership()
        caller, landing = wo.project_of(Path(cwd)), wo.project_of(fp)
        block = _check_project_boundary(cwd, caller, landing, fp)
        if block:
            return block

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
                return _refuse(reason)
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
                    return _refuse(reason)

        target_branch = _get_branch(str(fp.resolve()) if not fp.is_absolute() else str(fp), package)

        reason = wo.ownership_refusal(caller, landing, cwd, fp)
        if reason:
            return _refuse(reason)

        trinity_tools = ("Write", "Edit", "MultiEdit")
        if tool_name in trinity_tools and fp.parent.name == ".trinity" and fp.name in _TRINITY_MEMORY_FILES:
            if target_branch:
                block = _check_trinity_change(fp, tool_name, tool_input, target_branch)
                if block:
                    return block

        if not file_path.endswith(".py"):
            return {"stdout": "", "exit_code": 0}

        # A file the hook engine imports must not be left crashing at import.
        home = _import_module("aipass.hooks.apps.handlers.config.loader").aipass_home()
        crash = _import_module("aipass.hooks.apps.modules.engine_closure")
        block = crash.crash_refusal(fp, tool_name, tool_input, _resolve_after_text, home)
        if block:
            return _refuse(block)

        # Each seat reads its own diagnostics state alone.
        ds = _import_module("aipass.hooks.apps.modules.diagnostics_state")
        seat = ds.seat_key(hook_data)
        state = ds.load_seat(seat) or {}

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

        # Revalidate: a resolving write the hook did not observe (heredoc, editor) would block forever.
        fresh = ds.of_the_tree(errored, ds.revalidate(errored), 0)  # pyright counts from 0
        if fresh is not None:
            if not fresh:
                ds.clear_seat(seat)
                return {"stdout": "", "exit_code": 0}
            errors = fresh

        # Only-cross-file errors cannot justify the block: that is the red-first deadlock.
        if ds.all_cross_file(errors):
            logger.info(
                "[HOOKS] edit_gate: %d cross-file error(s) in %s — not blocking (resolve elsewhere)",
                len(errors),
                Path(errored_file).name,
            )
            return {"stdout": "", "exit_code": 0}

        error_summary = "\n".join(f"  L{e['line']}: {e['message']}" for e in errors[:5])
        reason = f"Fix {len(errors)} error(s) in {Path(errored_file).name} before editing other files:\n{error_summary}"
        return _refuse(reason)

    except Exception as exc:  # fail closed on what this gate guards
        logger.error("[HOOKS] edit_gate: crashed on %s, refusing it: %s", tool_name or "(no tool)", exc)
        if tool_name == "Bash" or tool_name in EDIT_TOOLS:
            return _refuse(GATE_CRASHED.format(error=f"{type(exc).__name__}: {exc}"))
        return {"stdout": "", "exit_code": 0}


def tripwire_snapshot(hook_data: dict) -> dict:
    """PreToolUse (Bash): record the seat's memory-file stats under this call's tool_use_id.

    Never blocks; a snapshot that cannot be taken leaves the call unwatched and logs it."""
    try:
        if hook_data.get("tool_name") != "Bash":
            return {"stdout": "", "exit_code": 0}
        dirs = _watched_trinity_dirs(hook_data.get("cwd", "") or os.getcwd())
        if not dirs:
            return {"stdout": "", "exit_code": 0}
        tool_use_id = hook_data.get("tool_use_id")
        if not tool_use_id:
            logger.info("[HOOKS] edit_gate tripwire: no tool_use_id in the payload, call unwatched")
            return {"stdout": "", "exit_code": 0}
        path = _tripwire_path(hook_data)
        pending = _read_pending(path)
        pending.pop(tool_use_id, None)
        # The dir list is stored, not rescanned: the comparison must be against what was measured.
        pending[tool_use_id] = {"trinity": str(dirs[0]), "stats": _memory_stats(dirs)}
        while len(pending) > _TRIPWIRE_PENDING_MAX:
            pending.pop(next(iter(pending)))
        scratch = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        scratch.write_text(json.dumps(pending), encoding="utf-8")
        os.replace(scratch, path)
    except Exception as exc:
        logger.warning("[HOOKS] edit_gate tripwire: snapshot failed, this call goes unwatched: %s", exc)
    return {"stdout": "", "exit_code": 0}


def _report_change(path: Path, seat: Path) -> tuple[list[str], bool]:
    """Report one changed memory file — loud when it does not measure clean, a question when it does.

    A clean change is said, not charged: another seat's compaction rolls THIS seat's local.json.
    Cases: docs/trinity_memory_gate.md."""
    findings = _measure_memory_file(path)
    mine = path.parent == seat
    if mine and not findings:
        clean = "It is inside its file budget." if path.name in _FILE_BUDGET_FILES else "It measures clean."
        return [
            f"MEMORY CHANGED DURING THIS BASH CALL: {path} changed during this Bash call, outside the caps gate. "
            f"{clean} If this command wrote it, memory is written with Edit/Write or a drone @memory verb, never "
            "a shell. It may not have been this command: @memory's rollover, run by any seat's compaction, "
            "writes here too."
        ], True
    if mine:
        head = f"MEMORY WRITTEN FROM A SHELL: {path} changed during this Bash call, outside the caps gate"
        cure = (
            "  Re-land each entry through Edit, trimming the over tail. Memory is written with Edit/Write "
            "or a drone @memory verb, never a shell."
        )
    else:
        head = f"ANOTHER BRANCH'S MEMORY CHANGED: {path} changed during this Bash call"
        cure = (
            f"  If this command wrote it, that is a cross-branch write — {path.parent.parent.name} owns that file. "
            "If that seat is live right now, this is its own write and there is nothing to do here."
        )
    if findings:
        return [f"{head}, and it does not measure clean:", *findings, cure], False
    clean = "It is inside its file budget." if path.name in _FILE_BUDGET_FILES else "It measures clean."
    return [f"{head}. {clean}", cure], True


def tripwire(hook_data: dict) -> dict:
    """PostToolUse (Bash): if the seat's memory changed during the call, measure it on disk and say so loudly.

    Compared against the same tool_use_id's snapshot, so a memory Edit just before the call is never blamed.
    A drone @memory or @spawn verb is the sanctioned writer. Never blocks: the command has already run."""
    try:
        if hook_data.get("tool_name") != "Bash":
            return {"stdout": "", "exit_code": 0}
        tool_use_id = hook_data.get("tool_use_id")
        before = _read_pending(_tripwire_path(hook_data)).get(tool_use_id) if tool_use_id else None
        if not isinstance(before, dict):
            if _seat_trinity(hook_data.get("cwd", "") or os.getcwd()) is not None:
                logger.info(
                    "[HOOKS] edit_gate tripwire: no snapshot for %s, cannot tell if memory changed", tool_use_id
                )
            return {"stdout": "", "exit_code": 0}

        trinity = Path(before["trinity"])
        stats_before: dict = before["stats"]
        now = _memory_stats(sorted({Path(key).parent for key in stats_before}))
        changed = [key for key in sorted(stats_before) if now.get(key) != stats_before[key]]
        if not changed:
            return {"stdout": "", "exit_code": 0}
        command = hook_data.get("tool_input", {}).get("command", "")
        if _runs_memory_verb(command, hook_data.get("cwd", "") or str(trinity.parent)):
            logger.info(
                "[HOOKS] edit_gate tripwire: %s changed by a drone memory verb (sanctioned)", ", ".join(changed)
            )
            return {"stdout": "", "exit_code": 0}

        parts: list[str] = []
        all_clean = True
        for key in changed:
            lines, clean = _report_change(Path(key), trinity)
            parts.extend(lines)
            all_clean = all_clean and clean
        context = "\n".join(parts)
        # A clean change is no defect, whoever made it: WARNING is what @trigger escalates.
        log = logger.info if all_clean else logger.warning
        log("[HOOKS] edit_gate tripwire: %s", context.replace("\n", " | "))
        output = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}}
        return {"stdout": json.dumps(output), "exit_code": 0}
    except Exception as exc:
        logger.warning("[HOOKS] edit_gate tripwire: failed, memory change unreported: %s", exc)
        return {"stdout": "", "exit_code": 0}
