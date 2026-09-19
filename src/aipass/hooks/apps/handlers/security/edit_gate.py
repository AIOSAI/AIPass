# =================== AIPass ====================
# Name: edit_gate.py
# Version: 1.16.0
# Description: Cross-project and who-owns-it (tool + scripted, modules/write_ownership), inbox and
#              shell-to-memory write protection (PreToolUse), plus the shell-memory tripwire
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-05-21
# Modified: 2026-09-18
# =============================================

"""Blocks unsafe edits: inbox, cross-project, cross-branch and shell-to-memory writes, daemon confinement, diagnostics
state. Reports a shell memory write the reader could not see, after the call."""

import importlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger


EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Who may write whose files (TRUSTED_CROSS_WRITERS, the project marker, the registry rows)
# lives in modules/write_ownership since the owner's ruling of 2026-09-18.
# The one seat that reaches outwards. The owner, 2026-08-30, compassed as devpulse
# entry 322: "It is only you who can reach outwards. Nobody else." The cross-
# project fence stays for every other agent, tool lane and scripted lane alike.
# Named here for the log line only — WHO is decided by modules/admin_seat's
# verified rail, never by this string matching a directory. Spelled rather than
# imported because a handler reaches modules through importlib at call time, not
# at import time (the branch's own architecture rule); modules/admin_seat holds
# the same literal and admin_seat_name() below is what keeps the two honest.
ADMIN_SEAT = "devpulse"
# passport.json joined these on 2026-09-15 (DPLAN-0347 rows 4 and 6). It is a
# .trinity file every bit as much as the other two, and until then it was
# writable by any lane at any size: the identity block renders on every cadence
# beat, so a passport that grows is a standing tax on the session. @spawn owns
# its schema, so it is measured by SIZE only — @memory's check_file_budget,
# 6,000 chars per file and 600 per string, never a field shape.
_TRINITY_MEMORY_FILES = frozenset({"local.json", "observations.json", "passport.json"})
_FILE_BUDGET_FILES = frozenset({"passport.json"})
# How deep under the project root a .trinity can sit: src/<pkg>/<branch>/.trinity
# is four. Bounded on purpose — a full walk of a repo this size on every Bash
# call is a cost no report is worth (24 dirs, 72 stats, ~19 ms measured 09-15).
_TRINITY_SCAN_DEPTH = 4
_NEWEST_FIRST_ARRAYS = ("sessions", "key_learnings")
_NUMBER_KEYS = ("number", "session_number")
# todos roll (DPLAN-0345, the owner 2026-09-14): over the pad count is legal on disk,
# and the oldest roll off to the branch's backlog FILE at its next rollover, never
# to vectors. The path is @memory's (todo_roll.backlog_path_for), spelled here.
_TODOS_COUNT_FALLBACK = 10
_TODO_BACKLOG = ".backup/todo/{branch}/backlog.json"
# The shell-memory tripwire (DPLAN-0342 row 3). One snapshot file per session in
# the temp dir, the home cadence's guard files already use. It holds the last few
# calls, keyed by tool_use_id, because a call whose PostToolUse never fires (a later
# gate refused it, the command failed) must not grow it.
_TRIPWIRE_DIR = Path(tempfile.gettempdir())
_TRIPWIRE_PENDING_MAX = 8
# The sanctioned writers of memory files from a shell: drone verbs, not raw writes.
_MEMORY_VERB_TARGETS = frozenset({"@memory", "@spawn"})
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")


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


def _ownership() -> Any:
    """modules/write_ownership, reached at call time: a handler never imports a module at import time."""
    return importlib.import_module("aipass.hooks.apps.modules.write_ownership")


def _refuse(reason: str) -> dict:
    return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": "edit gate"}


def _is_admin_seat(cwd: str) -> bool:
    """True only when the 5-leg admin grant verifies for this session.

    Delegates to ``modules/admin_seat.is_admin_seat`` — the implementation and
    its full reasoning moved there on 2026-09-01 when ``testwrite_gate`` needed
    the same answer. It stays spelled here as a name because a security
    exemption read two ways can disagree with itself, and the whole point of
    consuming @ai_mail's rail instead of mirroring it was to have one reading.

    Args:
        cwd: The session working directory from the hook payload.

    Returns:
        True when the grant verifies, False on every doubt.
    """
    try:
        admin = importlib.import_module("aipass.hooks.apps.modules.admin_seat")
    except Exception as exc:
        # The delegation must not become a way IN. Reaching the rail through a
        # second module adds a second import that can fail, and an exemption
        # that opens because a module was missing is worse than no exemption.
        logger.warning("[HOOKS] edit_gate: admin lane dark — admin_seat unavailable: %s", exc)
        return False
    return bool(admin.is_admin_seat(cwd))


def _check_project_boundary(cwd: str, caller: Any, landing: Any, target: Path) -> dict | None:
    """Block a write that crosses out of the caller's project, in any direction.

    Projects nest inside the host tree (projects/<name>). Every fence below this
    one keys on branch identity, which a project seat had none of before the
    registry rows were read: GH #733 measured a projects/baud session editing
    src/aipass/drone unchallenged while its mail to @drone was refused.

    Upward and sideways were always refused. Downward (the host into a project
    it contains) was trusted until the owner's ruling of 2026-09-18: "an AIPass
    agent must have no way to touch another project's files". Only the verified
    admin seat crosses now. *caller* and *landing* are write_ownership Projects.

    Returns a block dict, or None to allow.
    """
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
    return {
        "stdout": json.dumps({"decision": "block", "reason": reason}),
        "exit_code": 2,
        "sound": "edit gate",
    }


def _bash_write_targets(cwd: str, command: str) -> list[tuple[Path, str]]:
    """Every (path, how) the shell reader can see *command* write, read once for both Bash-lane rules.

    A parser that cannot read a command has learned nothing about it. Neither
    rule may convict on that, and neither may go quiet about it: the failure is
    logged and the answer is no targets.
    """
    if not command:
        return []
    try:
        bw = importlib.import_module("aipass.hooks.apps.modules.bash_writes")
        return bw.write_targets(command, cwd)
    except Exception as exc:
        logger.warning("[HOOKS] edit_gate: bash write-target scan failed (allowing): %s", exc)
        return []


def _check_bash_project_boundary(cwd: str, caller: Any, targets: list[tuple[Path, str]]) -> dict | None:
    """Block a cross-project write made through the shell rather than a tool.

    The tool lane was fenced and this one was not: @devpulse's Edit into a
    sibling project was refused on 2026-08-30 and ``sed -i`` on the same file
    went through, for every seat, not just the admin one. Same boundary, same
    direction rules, same refusal text — only the evidence differs, because a
    shell command names its targets in grammar rather than in a ``file_path``
    field.

    Scope is honest by construction: ``bash_writes`` reports only what it can
    SEE, and what it cannot see is enumerated in ``bash_writes.NOT_CAUGHT`` and
    repeated in the README. A parser that guessed would refuse correct commands,
    which is the failure mode that teaches agents to route around a gate.

    Returns a block dict, or None to allow.
    """
    if caller is None:
        return None
    wo = _ownership()
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

    The owner's ruling, 2026-09-18: own files only, on this lane as on the tool
    lane. Until then the shell lane read the project boundary alone, so any
    citizen could sed another branch. Convicts on write grammar only: an
    interpreter's held paths are left to the project fence (write_ownership).
    """
    wo = _ownership()
    for target, how in targets:
        reason = wo.ownership_refusal(caller, wo.project_of(target), cwd, target, how)
        if reason:
            logger.warning("[HOOKS] edit_gate: scripted write refused, not the seat's: %s via %s", target, how)
            return _refuse(reason)
    return None


def _check_bash_memory_write(targets: list[tuple[Path, str]]) -> dict | None:
    """Refuse a shell write to a .trinity memory file: every seat, every project, admin included.

    DPLAN-0342 row 3. @memory's caps are measured on the Edit/Write lane, so a
    write made from a shell landed unmeasured: @baud's 21 of 21 sessions went
    over cap that way on 08-16, @api 12 sessions and 16 learnings, @hooks 9
    entries on 2026-09-12. The reader built for the project fence already claims
    every shape that carried that drift (redirect, tee, sed -i, cp/mv, an
    interpreter holding the path), so the rule is one comparison on its targets.

    The admin exemption is not consulted. It lets one seat reach another
    project; it says nothing about how memory is written. An interpreter that
    only READS a memory path is refused too, because the interpreter rule cannot
    tell a read from a write. That over-refusal is named in the refusal, with
    the tools that read, rather than left for an agent to discover.

    Returns a block dict, or None to allow.
    """
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
        return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": "edit gate"}
    return None


def _memory_service_reachable() -> bool:
    """True when @memory's cap module imports from where this hook is running.

    Asked at refusal time, not at import: the same handler serves AIPass seats and
    `aipass init` projects, which have no @memory (docs/edit_gate.md).
    """
    try:
        importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")
        return True
    except Exception as exc:  # noqa: BLE001 - any import failure means "not reachable here"
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

    Carried debt must not be SILENT — that was the half of my 2026-08-27
    concern that was right, and @memory kept it when they reversed the rest:
    their writer logs a CARRIED line too. Not refused, not hidden, and not
    printed at the agent either: detection belongs to ``drone @memory lint``,
    which reads whole files on demand, rather than to a write gate that sees
    only the next write. INFO, because carrying inherited drift is not
    misbehaviour and a standing condition logged as a warning is what fed
    @trigger's escalation lane the last time.
    """
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

    The cap check reads one field name per entry type, taken from @memory's
    memory.config.json ``entry_limits`` (file/container/field). A renamed field
    — ``learning`` where the config says ``value``, the shape ai_mail, api and
    this branch carried — leaves the extractor with no such key. It answered
    ``""``, the entry measured as zero characters, and three branches ran 2.7x
    over cap for the two months AFTER the gate landed while it reported
    compliance. ``""`` and "cannot read this" are different answers; a field the
    gate cannot find is named, not measured.

    THE ON-DISK RULE IS NOW UNIVERSAL, not todos-only (2026-08-30, @memory's
    entry_limits 1.6.0). A write is refused for what it AUTHORS, never for what
    it CARRIES. I narrowed this to todos on 08-27 because the fleet had
    converged and "unchanged and over cap passes" looked like it hid new drift
    rather than protecting old. Both halves of that were wrong about the world,
    and @memory proved it from the outside: their rollover lane failed
    identically every 20 minutes for three hours because the extractor removed a
    tail, wrote the SMALLER document back, and a write gate refused the whole
    file over an entry in the head the extraction never touched. The archiver is
    always on the losing side of that trade — the file cannot get smaller
    because it is too big. My own refusal text is the other half of the
    evidence: writes made through Bash are not checked, so a write gate is
    structurally blind to how drift ARRIVES and cannot be the thing that
    detects it. That job belongs to ``drone @memory lint``, which reads the file.

    So this checker was fixed to match. @memory fixed their half and mine still
    deadlocked — measured live before this change: a write with an identical
    before and after still drew a refusal here. Identity is the raw entry, never
    the index: a prepend shifts every position down, and an index-keyed diff
    would call the whole file newly authored on exactly the write that authored
    nothing.

    Carrying a drifted entry still does not license adding another in the same
    shape — a NEW entry with a missing canonical field is authored, and refused.
    """
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
            # Plain-string entries carry their own text — measurable, and
            # @memory's extractor already handles them.
            if not isinstance(entry, dict) or field in entry:
                continue
            if entry in carried:
                # Byte-identical to disk: this write did not author it. Report,
                # never refuse — refusing here is what deadlocks the rollover
                # that is trying to shrink the very file being complained about.
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

    @memory's six-key record carries the measurement, not the text, and that
    shape is a published contract this gate does not get to grow. The text is
    where the record says it is: the entry type names the container and field,
    and the key is the dict key or list index in the SAME ``after`` document the
    extractor measured. Anything that does not resolve to a string of exactly the
    recorded length answers None — a cut drawn on text the record did not measure
    would point at the wrong characters, and the measurement line alone is still
    true without it.
    """
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

    The fleet's median overage is 7% of the cap and 88% of overages sit under
    20% — agents aim AT the line and land a few words past it. A refusal that
    only says "336/300 (+36)" makes the rewrite a re-guess of the whole entry;
    showing the 36 characters that crossed makes it a trim of a visible tail.
    Both halves are JSON-quoted so a trailing space or a newline at the boundary
    is visible, and ``len`` slices in code points — the unit the cap is measured
    in — so the bar sits exactly at the cap. Display only: the block is unchanged
    and nothing is ever truncated for the agent.
    """
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

    A refusal that cannot be measured must not print as a measurement. The
    unmeasurable and missing-field species carry zeros in length/cap/over_by to
    keep @memory's published six-key contract, so rendering them through the
    over-cap format produces "0/300 chars (+0)" — which reads as a bug in the
    gate rather than as the named refusal it is.

    @memory 1.11.0 (FPLAN-0593) adds two species to that contract —
    ``unknown_field`` and ``field_over_cap`` — plus ``file_over_budget`` from
    the passport row. Each carries ``field`` and ``units``; rendering them
    through the catch-all below would have called an over-cap status
    "unmeasurable", which is the opposite of what happened.
    """
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

    Two checkers now find the missing-field species: @memory's extractor (1.4.0,
    which stopped answering ``""`` for an absent key) and this gate's own
    ``_missing_field_violations``. The overlap is deliberate — a gate that
    outsources ALL of its measurement inherits its supplier's blind spots
    silently, which is how the renamed-field dodge survived two months — but one
    defect must still read as one defect. Two identical lines in a refusal send
    the agent hunting for a second problem that does not exist.

    Keyed on (entry_type, container, key): the container matters because two
    entry types both index their first entry as ``"0"``.
    """
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

    Read from @memory through ``fields_for`` rather than the raw key: the shape
    is memory's to publish and this gate's to render (DPLAN-0347). An
    unconfigured type answers {} and the refusal then says "the published
    shape" rather than naming an empty list.
    """
    if v.get("reason") != "unknown_field":
        return None
    try:
        fields = el.fields_for(v.get("entry_type", ""), limits)
    except AttributeError as exc:
        # An older @memory in the tree has no fields_for. The refusal is still
        # correct without the allow-list; going dark over a missing helper is not.
        logger.info("[HOOKS] edit_gate: fields_for unavailable, refusal renders without the shape: %s", exc)
        return None
    # Declaration order, not alphabetical: the config lists a field's own order
    # (number, date, summary, status, tags) and that reads as the entry's shape.
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
        # Say what this gate can actually see. The cap is measured on the
        # Edit/Write lane. Until DPLAN-0342 row 3 this line said a Bash write was
        # "not measured" — true, and three branches drifted over cap through that
        # lane (@baud to 2529/300 for a week, @api to 12 sessions + 16 learnings,
        # @hooks 9 entries). A shell write the reader can see is now refused
        # (_check_bash_memory_write); one it cannot see is reported after the
        # call by tripwire(). The carried-drift rule stays universal: a gate
        # blind to how drift ARRIVED cannot refuse a file for already carrying it.
        lines.append(
            "  (Caps are measured on Edit/Write; a write to a memory file made through Bash is refused. "
            "Cure drift already on disk with drone @memory lint.)"
        )
        return {
            "stdout": json.dumps({"decision": "block", "reason": "\n".join(lines)}),
            "exit_code": 2,
            "sound": "edit gate",
        }
    for v, text in zip(over, texts, strict=True):
        _log_violation(v, text)
    return None


def _evaluate_file_budget(file_name: str, after_text: str, limits: dict, el: Any) -> dict | None:
    """Measure a whole-file budget — the passport row (DPLAN-0347, @memory 1.11.0).

    SIZE only, never a field shape: @spawn owns passport.json's schema, @memory
    owns the numbers (6,000 chars per file, 600 per string), and this gate does
    what it is for — enforcing them at the write. The per-entry path above never
    saw a passport, because a passport carries no entry arrays.

    Warn-mode (``enforce`` false) logs and allows, exactly as the entry caps do.

    Args:
        file_name: The .trinity file being written, e.g. "passport.json".
        after_text: The file as it would be on disk after this call.
        limits: @memory's entry-limits block — read for its enforce switch.
        el: @memory's entry_limits module.

    Returns:
        A block dict, or None to allow.
    """
    if file_name not in _FILE_BUDGET_FILES:
        return None
    try:
        violations = el.check_file_budget(file_name, after_text)
    except AttributeError as exc:
        # An older @memory in the tree publishes no file budgets. Allow, and say
        # so once: a size rule that cannot be read is not a size rule that failed.
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
    return {
        "stdout": json.dumps({"decision": "block", "reason": "\n".join(lines)}),
        "exit_code": 2,
        "sound": "edit gate",
    }


def _todos_count_advisory(after: dict, branch: str) -> str:
    """Return advisory text if todos exceed rollover count limit, else empty string.

    Throttled to roughly one reminder per 10 turns (the owner's ruling,
    2026-08-19). Being over the cap is a STANDING condition — it stays true
    until the next rollover and re-asserts on every local.json edit — so firing
    per edit turned a correct advisory into 209 identical log lines and tripped
    @trigger's repeat-signature escalation. The log line throttles with the
    stdout line, not separately: escalation feeds on log repetition, so a
    silenced advisory that still writes a warning would fix nothing.

    The count is @memory's one resolver (config_loader.get_todos_count), the
    number its roll applies. The old per_branch-or-defaults read said a hardcoded
    10 for a per_branch local block without todos, where memory falls back to
    the configured default. With no usable count configured memory rolls
    nothing, and the text says so instead of promising a roll.

    Scope: only this count advisory softens. Hard entry-limit blocks and the
    newest-first checks are unchanged.
    """
    try:
        todos = after.get("todos")
        if not isinstance(todos, list):
            return ""
        cl = importlib.import_module("aipass.memory.apps.handlers.json.config_loader")
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
        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        if not cadence.should_fire_advisory("todos_count"):
            # debug, not info: the condition is unchanged and already recorded
            # by the emission that did fire. Volume is the defect here.
            logger.debug("[HOOKS] edit_gate: %s (throttled)", msg)
            return ""
        logger.warning("[HOOKS] edit_gate: %s", msg)
        return msg
    except Exception as exc:
        logger.warning("[HOOKS] edit_gate: todos count check failed (skipping): %s", exc)
        return ""


def _is_auto_compact(entry: Any) -> bool:
    """True for auto-compact snapshot entries.

    Must match rollover/extractor.py exactly. This guard and the extractor
    classifying the same entries differently is what made the warning
    unsatisfiable, so anything that is not a dict carrying
    status == "auto-compact" is a regular entry in both places.
    """
    return isinstance(entry, dict) and entry.get("status") == "auto-compact"


def _note_over_budget(branch: str, file_stem: str, label: str, count: int, cap: int) -> None:
    """Log one operator-facing line for a section over its rollover budget.

    Every clause is a claim the code keeps: the count is the number rollover
    itself counts, and @memory's detector marks the file ready at exactly this
    threshold, so the archival named here really does happen.

    INFO, not WARNING (compass #273, the owner 2026-08-14: severity follows design
    intent). Over-budget is not wrong behaviour — it is behaviour we chose to
    have, and the message itself says nothing is lost. As a WARNING this class
    fed @trigger's escalation lane: 8 signatures, 579 occurrences, 10 of the 62
    digests the lane has ever sent. The name says "note" so the level is not
    re-raised to match a verb.
    """
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

    Until DPLAN-0345 todos skipped this lane: they never rolled, so any trim claim
    was false. They roll now, one branch per call, to the backlog file and never
    to vectors, so "recall them with drone @memory search" would be the false
    clause. INFO for the same reason as _note_over_budget.
    """
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

    Snapshots carry their own small cap in the extractor and never count against
    the regular session budget. Checking the combined array against the regular
    cap made this warning permanently unsatisfiable: a branch sitting legally at
    14 regular + 2 snapshots read 16/15 on every .trinity write while rollover
    correctly archived nothing, so the promised trim could never arrive.
    """
    auto_cap = section_cfg.get("auto_compact_cap")
    if auto_cap is not None:
        snapshots = [e for e in entries if _is_auto_compact(e)]
        if len(snapshots) > auto_cap:
            _note_over_budget(branch, file_stem, "sessions (auto-compact snapshots)", len(snapshots), auto_cap)

    cap = section_cfg.get("count")
    if cap is not None:
        # Unconditional split, matching the extractor: it excludes snapshots from
        # the regular count whether or not auto_compact_cap is configured.
        regular = [e for e in entries if not _is_auto_compact(e)]
        if len(regular) > cap:
            _note_over_budget(branch, file_stem, "sessions", len(regular), cap)


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


def _unparseable_refusal(fp: Path, exc: ValueError) -> dict:
    """Refuse a memory write whose RESULT does not parse — the file would be broken for every reader.

    Until 2026-09-16 this fell into the catch-all below and was ALLOWED. Every
    writer is atomic, so an unparseable memory file is a complete file an edit
    broke; refusing the edit means it never breaks. Why this and not a reader
    grace window: docs/trinity_memory_gate.md.
    """
    reason = (
        f"{fp.name}: this edit would leave the file unparseable as JSON ({exc}). A memory file that does "
        "not parse is broken for every reader until the next edit lands — @memory, this gate, the tripwire "
        "and the startup read all see a corrupt seat. Make the edit so the whole file still parses, then retry."
    )
    return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": "edit gate"}


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
            # Already broken on disk and this edit parses: it is the repair, so no caps against it.
            logger.warning(
                "[HOOKS] edit_gate: %s did not parse before this %s, which repairs it: %s", fp, tool_name, exc
            )
            return None

        block = _check_newest_first(before, after)
        if block:
            return block

        el = importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")
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
                # Context, not plain stdout: on a PreToolUse exit 0 Claude Code shows
                # plain stdout in the transcript view and never hands it to the model,
                # and the model writing the 11th todo is the audience (@canary
                # measured it, 2026-09-15). No permissionDecision: this never decides.
                output = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": advisory}}
                return {"stdout": json.dumps(output), "exit_code": 0}

        return None
    except Exception as exc:
        logger.warning("[HOOKS] edit_gate: .trinity size check failed (allowing): %s", exc)
        return None


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

    DPLAN-0347 row 4. The tripwire used to watch the seat alone, so a shell write
    into ANOTHER branch's memory — the shape the cross-branch fence exists to
    refuse, arriving by a path the reader cannot see — landed unreported. A stat
    is all it takes to notice, and no file is read unless something changed.
    """
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

    None for a missing file, so a creation or a removal reads as a change. Keyed
    by path rather than name because the tripwire now watches every .trinity in
    the project and two branches have the same three file names.
    """
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
    bw = importlib.import_module("aipass.hooks.apps.modules.bash_writes")
    for segment, _hits in bw.write_targets_by_segment(command, cwd):
        words = list(segment)
        while words and _ENV_ASSIGNMENT.match(words[0]):
            words.pop(0)
        if len(words) > 1 and Path(words[0]).name == "drone" and words[1] in _MEMORY_VERB_TARGETS:
            return True
    return False


def _measure_memory_file(path: Path) -> list[str]:
    """What a memory file holds that fails its caps, rendered as the Edit refusal renders it, cut point included.

    The WHOLE file is measured, not a diff: the snapshot holds stats, not text,
    so an entry already over cap before the call is listed too. The report says
    "holds", never "wrote".
    """
    if not path.is_file():
        return [f"  {path.name} no longer exists."]
    if path.name in _FILE_BUDGET_FILES:
        el = importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")
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
    el = importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")
    limits = el.load_entry_limits(path.parent.parent.name)
    if not limits.get("enabled"):
        return []
    over = _dedupe_violations(el.changed_entries({}, doc, limits))
    return [_format_violation(v, None if v.get("reason") else _entry_text(v, doc, limits)) for v in over]


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

        # The scripted lane. Three rules run on what the shell reader can see: the
        # project fence, the memory rule (a .trinity memory file is written where
        # its caps are measured, never from a shell — DPLAN-0342 row 3), and whose
        # file it is (the owner's ruling, 2026-09-18). The inbox and daemon checks
        # read a single named file, and a shell command has no such field. What the
        # reader cannot see is published in bash_writes.NOT_CAUGHT; a memory write
        # among it is reported after the call by tripwire().
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
            return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": "edit gate"}

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

        ds = importlib.import_module("aipass.hooks.apps.modules.diagnostics_state")
        state = ds.load()

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

        # The block must describe what is true now, not what was true when auto_fix
        # last ran. Any resolving write the hook did not observe — a Bash heredoc, an
        # external editor — used to leave the state behind and block forever.
        fresh = ds.revalidate(errored)
        if fresh is not None:
            if not fresh:
                ds.clear()
                return {"stdout": "", "exit_code": 0}
            errors = fresh

        # An error that can only be fixed in another file cannot justify blocking edits
        # to other files: that is the red-first deadlock, unsatisfiable by any allowed
        # action. A single locally-fixable error among them keeps the block.
        if ds.all_cross_file(errors):
            logger.info(
                "[HOOKS] edit_gate: %d cross-file error(s) in %s — not blocking (resolve elsewhere)",
                len(errors),
                Path(errored_file).name,
            )
            return {"stdout": "", "exit_code": 0}

        error_summary = "\n".join(f"  L{e['line']}: {e['message']}" for e in errors[:5])
        reason = f"Fix {len(errors)} error(s) in {Path(errored_file).name} before editing other files:\n{error_summary}"
        return {
            "stdout": json.dumps({"decision": "block", "reason": reason}),
            "exit_code": 2,
            "sound": "edit gate",
        }

    except Exception as exc:
        logger.warning("[HOOKS] edit_gate: unexpected error, every fence dark for this call (allowing): %s", exc)
        return {"stdout": "", "exit_code": 0}


def tripwire_snapshot(hook_data: dict) -> dict:
    """PreToolUse (Bash): record the seat's memory-file stats under this call's tool_use_id.

    The first half of the shell-memory tripwire; :func:`tripwire` is the second.
    Never blocks. A snapshot that cannot be taken leaves the call unwatched and
    says so in the log.
    """
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
        # The dir list is stored, not rescanned at PostToolUse: the comparison must
        # be against what was measured, and a rescan would also pay the glob twice.
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

    A clean change is said, not charged, even for the seat's own file: another
    seat's compaction rolls THIS seat's local.json (measured 2026-09-16). An
    unclean change keeps the accusation and the cure. Cases: docs/trinity_memory_gate.md.

    Args:
        path: The changed memory file.
        seat: The seat's own .trinity directory, from the snapshot.

    Returns:
        (lines, clean) — lines for the report, already indented where they
        belong, and whether the file measured clean.
    """
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

    DPLAN-0342 row 3, the belt to the Bash-lane refusal's braces. The refusal
    covers every shell write the reader can SEE; this reports the ones it cannot
    (a bare file name after cd, a path joined in program text, a path in a shell
    variable) the moment they land, instead of weeks later in an audit nobody
    ran. The comparison is against the snapshot :func:`tripwire_snapshot` took
    for the same tool_use_id, so a memory Edit made just before the call is never
    blamed on it. A drone @memory or @spawn verb is the sanctioned writer and is
    not reported. Never blocks: the command has already run.
    """
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
