# =================== AIPass ====================
# Name: edit_gate.py
# Version: 1.9.0
# Description: Cross-project (tool + scripted), cross-branch and inbox write protection (PreToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-05-21
# Modified: 2026-09-01
# =============================================

"""Blocks unsafe edits: inbox writes, cross-project and cross-branch writes, daemon confinement, diagnostics state."""

import importlib
import json
import os
from pathlib import Path
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger


EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
TRUSTED_CROSS_WRITERS: tuple[str, ...] = ("devpulse", "seedgo", "spawn")
# The one seat that reaches outwards. Patrick, 2026-08-30, compassed as devpulse
# entry 322: "It is only you who can reach outwards. Nobody else." The cross-
# project fence stays for every other agent, tool lane and scripted lane alike.
# Named here for the log line only — WHO is decided by modules/admin_seat's
# verified rail, never by this string matching a directory. Spelled rather than
# imported because a handler reaches modules through importlib at call time, not
# at import time (the branch's own architecture rule); modules/admin_seat holds
# the same literal and admin_seat_name() below is what keeps the two honest.
ADMIN_SEAT = "devpulse"
# A project root is the directory holding a *_REGISTRY.json — the same marker
# @ai_mail's find_project_root uses (handlers/paths.py). Deliberately identical:
# the file fence and the mail fence must draw the boundary in the same place, or
# an agent is refused a send and allowed the equivalent write (GH #733).
_PROJECT_MARKER = "*_REGISTRY.json"
_TRINITY_MEMORY_FILES = frozenset({"local.json", "observations.json"})
_NEWEST_FIRST_ARRAYS = ("sessions", "key_learnings")
_NUMBER_KEYS = ("number", "session_number")
# todos never roll — they are operational and pruned by hand. _todos_count_advisory
# says so in the right words; the rollover-budget warning must not also claim a trim.
_NON_ROLLING_SECTIONS = frozenset({"todos"})


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


def _find_project_root(start: Path) -> Path | None:
    """Return the nearest ancestor of *start* holding a *_REGISTRY.json, or None.

    Mirrors @ai_mail's find_project_root. Returns None rather than raising on an
    unreadable path — a fence that cannot locate a boundary must not invent one.
    """
    try:
        current = start.resolve()
    except OSError as exc:
        logger.info("[HOOKS] edit_gate: project root unresolvable for %s: %s", start, exc)
        return None
    for candidate in [current] + list(current.parents):
        try:
            if any(candidate.glob(_PROJECT_MARKER)):
                return candidate
        except OSError as exc:
            logger.info("[HOOKS] edit_gate: project marker scan failed at %s: %s", candidate, exc)
            break
    return None


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


def _check_project_boundary(cwd: str, target: Path) -> dict | None:
    """Block a write that crosses out of the caller's project.

    Projects nest inside the host tree (projects/<name>) but are its least-trusted
    layer. Every fence below this one keys on the src/<package>/<branch> shape,
    which no project seat has: both sides resolved to an empty branch and the write
    fell through to allow. GH #733 measured the result — a projects/baud session
    edited src/aipass/drone unchallenged, while the same agent's mail to @drone was
    correctly refused.

    Direction matters, so this is not symmetric with the mail fence:
      - upward (nested project -> host) and sideways (project -> sibling): blocked.
      - downward (host -> a project it contains): allowed. Trust runs downward, and
        the host tree carries artifact registries of its own (flow_json/
        PLAN_REGISTRY.json, .backup snapshots) that would otherwise read as foreign
        projects to the very branches that own them.

    Returns a block dict, or None to allow.
    """
    caller_root = _find_project_root(Path(cwd))
    if caller_root is None:
        return None
    target_root = _crossing_root(caller_root, target)
    if target_root is None:
        return None
    if _is_admin_seat(cwd):
        logger.info(
            "[HOOKS] edit_gate: cross-project write ALLOWED for the admin seat (@%s): %s -> %s (%s)",
            ADMIN_SEAT,
            caller_root.name,
            target_root.name,
            target,
        )
        return None

    logger.warning(
        "[HOOKS] edit_gate: cross-project write refused: caller root %s != target root %s (%s)",
        caller_root,
        target_root,
        target,
    )
    return _cross_project_block(caller_root, target_root, target, "")


def _crossing_root(caller_root: Path, target: Path) -> Path | None:
    """Return the foreign project root *target* lands in, or None if it stays home.

    The direction rules live here alone so the tool lane and the scripted lane
    cannot answer the same question differently — which is exactly how the
    scripted lane came to be open while the tool lane was fenced.

    The walk starts AT *target*, not at its parent: a bash operand can name a
    directory (``mkdir``, ``cp -r``), and starting at the parent would read a
    write to a project root as a write to the tree that contains it.
    """
    target_root = _find_project_root(target)
    if target_root is None or target_root == caller_root:
        return None
    if caller_root in target_root.parents:
        return None
    return target_root


def _cross_project_block(caller_root: Path, target_root: Path, target: Path, how: str) -> dict:
    """Build the refusal both lanes print. *how* names the shell verb, or "" for a tool edit."""
    lane = f"Cross-project write blocked ({how})" if how else "Cross-project write blocked"
    reason = (
        f"{lane}: project '{caller_root.name}' cannot write into project '{target_root.name}'.\n"
        f"Target: {target}\n"
        "A project writes inside itself only — never into its host or a sibling. This is the "
        "file-layer twin of the mail fence that refuses cross-project sends.\n"
        'To reach that project: drone @devpulse feedback send "Subject" "Body"'
    )
    return {
        "stdout": json.dumps({"decision": "block", "reason": reason}),
        "exit_code": 2,
        "sound": "edit gate",
    }


def _check_bash_project_boundary(cwd: str, command: str) -> dict | None:
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
    if not command:
        return None
    caller_root = _find_project_root(Path(cwd))
    if caller_root is None:
        return None
    try:
        bw = importlib.import_module("aipass.hooks.apps.modules.bash_writes")
        targets = bw.write_targets(command, cwd)
    except Exception as exc:
        # A parser that cannot read a command has learned nothing about it. It
        # must not convict on that, and it must not go quiet about it either.
        logger.warning("[HOOKS] edit_gate: bash write-target scan failed (allowing): %s", exc)
        return None

    for target, how in targets:
        target_root = _crossing_root(caller_root, target)
        if target_root is None:
            continue
        if _is_admin_seat(cwd):
            logger.info(
                "[HOOKS] edit_gate: scripted cross-project write ALLOWED for the admin seat (@%s): %s -> %s (%s)",
                ADMIN_SEAT,
                caller_root.name,
                target_root.name,
                target,
            )
            return None
        logger.warning(
            "[HOOKS] edit_gate: scripted cross-project write refused: %s -> %s via %s (%s)",
            caller_root,
            target_root,
            how,
            target,
        )
        return _cross_project_block(caller_root, target_root, target, how)
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


def _format_violation(v: dict) -> str:
    """Render one violation line.

    A refusal that cannot be measured must not print as a measurement. The
    unmeasurable and missing-field species carry zeros in length/cap/over_by to
    keep @memory's published six-key contract, so rendering them through the
    over-cap format produces "0/300 chars (+0)" — which reads as a bug in the
    gate rather than as the named refusal it is.
    """
    reason = v.get("reason")
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
    return f"  {v['entry_type']} [{v['key']}]: {v['length']}/{v['cap']} chars (+{v['over_by']})"


def _log_violation(v: dict) -> None:
    """Warn-mode log line — carries the same cause the block would have named."""
    if v.get("reason"):
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
        "[HOOKS] edit_gate: over-limit .trinity entry %s [%s]: %d/%d (+%d) — warn only",
        v["entry_type"],
        v["key"],
        v["length"],
        v["cap"],
        v["over_by"],
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


def _evaluate_limits(before: dict, after: dict, limits: dict, el: Any) -> dict | None:
    """Diff changed entries and return block dict or None (allow)."""
    over = el.changed_entries(before, after, limits)
    over = _dedupe_violations(over + _missing_field_violations(before, after, limits))
    if not over:
        return None
    if limits.get("enforce"):
        lines = ["Unwritable .trinity entries (fix before saving):"]
        for v in over:
            lines.append(_format_violation(v))
        # Say what this gate can actually see. Bash now reaches this handler, but
        # only its PROJECT fence — the cap check runs on the Edit/Write lane alone,
        # so a write made through python -c, a heredoc or sed is still unmeasured.
        # Three branches have drifted over cap through that lane — @baud to
        # 2529/300 for a week, @api to 12 sessions + 16 learnings. Claiming
        # enforcement it does not have is what let the drift read as compliance.
        # Same reason the on-disk pass is universal: a gate blind to how drift
        # ARRIVES cannot be the thing that refuses a file for already carrying it.
        lines.append(
            "  (Caps are measured on Edit/Write only — a write made through Bash is not measured. "
            "Cure drift already on disk with drone @memory lint.)"
        )
        return {
            "stdout": json.dumps({"decision": "block", "reason": "\n".join(lines)}),
            "exit_code": 2,
            "sound": "edit gate",
        }
    for v in over:
        _log_violation(v)
    return None


def _todos_count_advisory(after: dict, branch: str) -> str:
    """Return advisory text if todos exceed rollover count limit, else empty string.

    Throttled to roughly one reminder per 10 turns (Patrick's ruling,
    2026-08-19). Being over the cap is a STANDING condition — it stays true for
    days and re-asserts on every local.json edit — so firing per edit turned a
    correct advisory into 209 identical log lines and tripped @trigger's
    repeat-signature escalation. The log line throttles with the stdout line,
    not separately: escalation feeds on log repetition, so a silenced advisory
    that still writes a warning would fix nothing.

    Scope: only this count advisory softens. Hard entry-limit blocks and the
    newest-first checks are unchanged.
    """
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

    INFO, not WARNING (compass #273, Patrick 2026-08-14: severity follows design
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
            if section_name in _NON_ROLLING_SECTIONS:
                continue
            entries = after.get(section_name)
            if not isinstance(entries, list):
                continue

            if section_name == "sessions":
                _check_session_counts(branch, file_stem, entries, section_cfg)
                continue

            cap = section_cfg.get("count")
            if cap is not None and len(entries) > cap:
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

        # The scripted lane. Only the project fence runs here — the branch,
        # inbox, daemon and .trinity checks read a single named file, and a
        # shell command has no such field to read. Claiming they apply would be
        # the enforcement-it-does-not-have mistake the caps advisory already
        # names out loud.
        if tool_name == "Bash":
            cwd = hook_data.get("cwd", "") or os.getcwd()
            return _check_bash_project_boundary(cwd, tool_input.get("command", "")) or {
                "stdout": "",
                "exit_code": 0,
            }

        if tool_name not in EDIT_TOOLS:
            return {"stdout": "", "exit_code": 0}

        if not file_path:
            return {"stdout": "", "exit_code": 0}

        fp = Path(file_path)
        if fp.name == "inbox.json" and ".ai_mail.local" in fp.parts:
            reason = 'Direct writes to inbox.json are blocked.\nUse: drone @ai_mail email @<branch> "Subject" "Body"'
            return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": "edit gate"}

        cwd = hook_data.get("cwd", "") or os.getcwd()

        # Outermost boundary first: a project seat has no branch identity in the
        # checks below, so it must be fenced before they can fall through to allow.
        block = _check_project_boundary(cwd, fp)
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
        logger.info("[HOOKS] edit_gate: unexpected error (allowing): %s", exc)
        return {"stdout": "", "exit_code": 0}
