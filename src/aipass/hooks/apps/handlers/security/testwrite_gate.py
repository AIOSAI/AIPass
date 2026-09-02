# =================== AIPass ====================
# Name: testwrite_gate.py
# Version: 1.0.0
# Description: Blocks agent creation of NEW test files behind a JSON policy switch (PreToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""Enforces Patrick's 2026-09-01 ruling: agents do not create tests for now.

The ruling (devpulse DPLAN-0323): while @seedgo's test_quality v5 pack lands,
agents are stripped of self-directed test creation. The corpus that ruling is
draining — tests written to satisfy a checker rather than to pin a defect —
regrows faster than a standards pack can cull it, so the cull needs a gate in
front of it.

WHAT IS BLOCKED: the CREATION of a pytest-collectable file inside a ``tests/``
tree, on both lanes — the tool lane (Edit/Write/MultiEdit/NotebookEdit) and the
scripted lane (Bash, read through ``bash_writes``, the same parser edit_gate's
cross-project fence uses).

WHAT IS NOT: edits to test files that already exist. An agent fixing a red test
is doing legitimate work, and this ruling is about the corpus GROWING. That is
a config field (``block_test_edits``), shipped false, live rather than dormant
— a switch nobody has ever executed is not a switch, it is an untested branch,
and the whole design brief here was that later changes are field flips and not
rebuilds.

ORDER OF QUESTIONS, and each one is load-bearing:

 1. Is any target a test file at all? If not, return immediately — the policy
    is never read. This is what makes the fail-closed policy safe: a missing or
    corrupt policy cannot brick ordinary work, only test creation.
 2. Is this the admin seat? Verified through the same 5-leg grant rail
    edit_gate uses (``modules/admin_seat``), consulted BEFORE the policy so
    that cleanup work with Patrick survives a broken policy file.
 3. What does the policy say? See ``modules/testgate_policy`` for the
    fail-closed ruling and why it differs from bash_writes' allow-and-log.

What this gate cannot see is published as data in
``testwrite_targets.NOT_CAUGHT`` and printed by ``drone @hooks testwrite``.
"""

import importlib
import json
import os
from pathlib import Path
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Log-line only; modules/admin_seat's verified rail decides WHO. Spelled rather
# than imported at module scope — see _module() on why handlers reach sideways
# at call time.
ADMIN_SEAT = "devpulse"
_ALLOW = {"stdout": "", "exit_code": 0}
_SOUND = "edit gate"


def _module(name: str) -> Any:
    """Reach a sibling module at CALL time, never at import time.

    A handler importing ``apps.modules`` at module scope is the orchestration
    inversion @seedgo's architecture check names, and it also drags every
    module's imports into every hook process. edit_gate reaches bash_writes and
    diagnostics_state exactly this way.

    Args:
        name: Module name under ``aipass.hooks.apps.modules``.

    Returns:
        The imported module.
    """
    return importlib.import_module(f"aipass.hooks.apps.modules.{name}")


def _is_admin_seat(cwd: str) -> bool:
    """True only when the 5-leg admin grant verifies, fail-closed at every edge.

    An unimportable ``admin_seat`` refuses rather than raises: the delegation
    must not become a way IN, and an exemption that opens because a module was
    missing is worse than no exemption at all.

    Args:
        cwd: The session working directory from the hook payload.

    Returns:
        True when the grant verifies, False on every doubt.
    """
    try:
        return bool(_module("admin_seat").is_admin_seat(cwd))
    except Exception as exc:
        logger.warning("[HOOKS] testwrite_gate: admin lane dark — admin_seat unavailable: %s", exc)
        return False


def _block(reason: str) -> dict:
    """Build the refusal both lanes print."""
    return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": _SOUND}


def _caller_branch(cwd: str) -> str:
    """Name the branch a session is standing in, or "" when it is not in one.

    Reads the ``src/<package>/<branch>`` shape rather than an env var: a hook
    process inherits whatever the session exported, and the ``allow`` array
    decides who is exempt from a ruling — that must key on where the write is
    actually being made from, not on a name the session could set for itself.

    Args:
        cwd: The session working directory from the hook payload.

    Returns:
        The branch name, or "" when the path has no branch shape.
    """
    parts = Path(cwd).parts
    for i, part in enumerate(parts):
        if part == "src" and i + 2 < len(parts):
            return parts[i + 2]
    return ""


def _targets(tool_name: str, tool_input: dict, cwd: str) -> list[Path]:
    """Every write target this event can be seen to name.

    Two lanes, one classification. The scripted lane reuses ``bash_writes``
    rather than growing a second shell reader — a gate that reads commands
    differently from the fence beside it will one day disagree with it.

    Args:
        tool_name: The tool the platform is about to run.
        tool_input: That tool's input payload.
        cwd: The session working directory relative paths resolve against.

    Returns:
        Resolved candidate paths, possibly empty.
    """
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if not command:
            return []
        try:
            return [target for target, _why in testwrite_targets_bash(command, cwd)]
        except Exception as exc:
            # A parser that cannot read a command has learned nothing about it.
            # It must not convict on that, and it must not go quiet either.
            logger.warning("[HOOKS] testwrite_gate: bash write-target scan failed (allowing): %s", exc)
            return []

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return []
    return [Path(file_path)]


def testwrite_targets_bash(command: str, cwd: str) -> list[tuple[Path, str]]:
    """Thin seam onto ``bash_writes.write_targets`` so tests can pin the reuse.

    Args:
        command: The raw Bash command string.
        cwd: The session working directory.

    Returns:
        The (path, why) pairs bash_writes reports.
    """
    return _module("bash_writes").write_targets(command, cwd)


def _refuse_creation(targets: list[Path], policy: Any, branch: str, lane: str) -> dict:
    """Build the refusal for a blocked CREATION, naming the config and the cure."""
    named = "\n".join(f"  {t}" for t in targets)
    who = f"branch '{branch}'" if branch else "this session"
    reason = (
        f"New test file blocked ({lane}): agents do not create tests right now.\n"
        f"{named}\n\n"
        "Patrick's ruling, 2026-09-01 (DPLAN-0323): self-directed test creation is off across "
        "the fleet while @seedgo's test_quality v5 pack lands. Editing an EXISTING test to fix "
        "a red is still allowed — this is about the corpus growing, not about freezing it.\n\n"
        f"Policy: {policy.path}\n"
        f'  to lift for one branch : add "{branch or "<branch>"}" to the "allow" array\n'
        '  to lift fleet-wide     : set "agent_test_writing" to "on"\n'
        f"  to read it here        : drone @hooks testwrite\n\n"
        f"This is a human ruling, not a lint — {who} cannot flip it. Ask Patrick or @devpulse "
        'if the test is needed: drone @ai_mail email @devpulse "Subject" "Body"'
    )
    return _block(reason)


def _refuse_edit(targets: list[Path], policy: Any, lane: str) -> dict:
    """Build the refusal for a blocked EDIT, live only when block_test_edits is flipped on."""
    named = "\n".join(f"  {t}" for t in targets)
    reason = (
        f"Test file edit blocked ({lane}): this project has test EDITS switched off too.\n"
        f"{named}\n\n"
        f'Policy: {policy.path} — "block_test_edits" is true.\n'
        '  to allow edits again: set "block_test_edits" to false\n'
        "  to read the policy  : drone @hooks testwrite"
    )
    return _block(reason)


def _refuse_unreadable(targets: list[Path], policy: Any, lane: str) -> dict:
    """Build the fail-closed refusal for a missing or corrupt policy."""
    named = "\n".join(f"  {t}" for t in targets)
    reason = (
        f"New test file blocked ({lane}): {policy.error}\n"
        f"{named}\n\n"
        "Only test-file CREATION is affected — every other write is untouched by this gate, "
        "and writing the policy file is not itself a test write, so this is repairable from "
        "right here.\n"
        "  drone @hooks testwrite   shows what this gate can see"
    )
    return _block(reason)


def handle(hook_data: dict) -> dict:
    """Apply the test-write policy and return a block or allow decision.

    Args:
        hook_data: Parsed hook event dict from the engine.

    Returns:
        Result dict with stdout (block JSON or empty) and exit_code.
    """
    try:
        tool_name = hook_data.get("tool_name", "")
        if tool_name != "Bash" and tool_name not in EDIT_TOOLS:
            return _ALLOW

        tool_input = hook_data.get("tool_input", {}) or {}
        cwd = hook_data.get("cwd", "") or os.getcwd()
        lane = "scripted" if tool_name == "Bash" else "tool"

        targets = _module("testwrite_targets")
        created, edited = targets.classify(_targets(tool_name, tool_input, cwd))
        if not created and not edited:
            # The policy is deliberately NOT read here. Ordinary work must not be
            # reachable by a broken policy file — see modules/testgate_policy.
            return _ALLOW

        if _is_admin_seat(cwd):
            logger.info(
                "[HOOKS] testwrite_gate: test write ALLOWED for the admin seat (@%s): %s",
                ADMIN_SEAT,
                [str(p) for p in created + edited],
            )
            return _ALLOW

        policy = _module("testgate_policy").load(cwd)
        if policy.error:
            if not created:
                # A policy we cannot read says nothing about edits either, but the
                # ruling it stands in for only ever blocked creation. Refusing an
                # edit on an unreadable file would extend a ruling by accident.
                logger.warning("[HOOKS] testwrite_gate: policy unreadable, edit-only write allowed: %s", policy.error)
                return _ALLOW
            logger.warning("[HOOKS] testwrite_gate: refusing (fail-closed): %s", policy.error)
            return _refuse_unreadable(created, policy, lane)

        branch = _caller_branch(cwd)
        if policy.writing_enabled or branch in policy.allow:
            logger.info(
                "[HOOKS] testwrite_gate: test write allowed (writing_enabled=%s, branch=%s): %s",
                policy.writing_enabled,
                branch or "<none>",
                [str(p) for p in created + edited],
            )
            return _ALLOW

        if created:
            logger.warning(
                "[HOOKS] testwrite_gate: new test file refused for '%s' via the %s lane: %s",
                branch or "<no branch>",
                lane,
                [str(p) for p in created],
            )
            return _refuse_creation(created, policy, branch, lane)

        if edited and policy.block_edits:
            logger.warning(
                "[HOOKS] testwrite_gate: test EDIT refused (block_test_edits on): %s",
                [str(p) for p in edited],
            )
            return _refuse_edit(edited, policy, lane)

        return _ALLOW

    except Exception as exc:
        # Crash isolation: a gate that dies must not take the write with it. The
        # fail-CLOSED ruling covers a policy this gate could not READ; it does not
        # cover a defect in this gate, which is ours and must be loud, not a wall.
        logger.error("[HOOKS] testwrite_gate: unexpected error (allowing): %s", exc)
        return _ALLOW
