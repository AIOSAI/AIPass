# =================== AIPass ====================
# Name: testwrite_gate.py
# Version: 1.4.1
# Description: Blocks agent creation of NEW test files (PreToolUse) + the test template pointer (PostToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-09-01
# Modified: 2026-10-25
# =============================================

"""Enforces the owner's 2026-09-01 ruling: agents do not create tests for now.

Failure mode: a crash refuses the write it was checking; the engine refuses on import error and timeout.

Blocks the CREATION of a test file on both lanes (tool, and Bash via bash_writes); edits pass unless
block_test_edits is on. Non-test targets return before the policy is read: a broken policy cannot brick other work.
"""

import importlib
import json
import os
from pathlib import Path
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Log-line only; modules/admin_seat's verified rail decides WHO.
ADMIN_SEAT = "devpulse"
_ALLOW = {"stdout": "", "exit_code": 0}
_SOUND = "edit gate"


def _module(name: str) -> Any:
    """Reach a sibling module at CALL time, never at import time."""
    return importlib.import_module(f"aipass.hooks.apps.modules.{name}")


def _is_admin_seat(cwd: str) -> bool:
    """True only when the 5-leg admin grant verifies, fail-closed at every edge.

    An unimportable admin_seat refuses: a missing module must never open the exemption.
    """
    try:
        return bool(_module("admin_seat").is_admin_seat(cwd))
    except Exception as exc:
        logger.warning("[HOOKS] testwrite_gate: admin lane dark — admin_seat unavailable: %s", exc)
        return False


GATE_CRASHED = (
    "testwrite_gate could not check this call ({error}), so it is refused: a gate that cannot read a call "
    "does not let it through.\n"
    'Mail @hooks and @devpulse: drone @ai_mail email @hooks "Gate broken: testwrite_gate" "<what you ran, and this text>"'
)


def _block(reason: str) -> dict:
    """Build the refusal both lanes print."""
    return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": _SOUND}


def _caller_branch(cwd: str) -> str:
    """Name the branch a session is standing in, or "" when it is not in one.

    Reads the path, not an env var: the session could set its own name to join the allow array.
    """
    parts = Path(cwd).parts
    for i, part in enumerate(parts):
        if part == "src" and i + 2 < len(parts):
            return parts[i + 2]
    return ""


def _targets(tool_name: str, tool_input: dict, cwd: str) -> list[Path]:
    """Every write target this event can be seen to name.

    Bash reuses bash_writes so this gate never reads a command differently from edit_gate's fence.
    """
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if not command:
            return []
        # A command the parser cannot read raises into handle()'s crash refusal.
        return [target for target, _why in testwrite_targets_bash(command, cwd)]

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return []
    return [Path(cwd) / file_path]  # relative to the payload's cwd, never this process's


# A `-m <runner>` run executes existing tests and creates no file; a bare `python script.py` can write anything.
_TEST_RUNNER_MODULES = frozenset({"pytest", "unittest"})

# bash_writes' interpreter reason: right for edit_gate's fence, too broad for "is a new test created".
_INTERPRETER_REASON = "(interpreter — may write any path it holds)"

# Read from bash_writes, never restated, so a renamed marker cannot drift; absent means no evidence either way.
_NO_WRITE_VERB_ATTR = "NO_WRITE_VERB"


def _is_test_run(segment: list[str]) -> bool:
    """True when this segment merely RUNS tests."""
    for index, token in enumerate(segment):
        if token == "-m" and index + 1 < len(segment):
            return segment[index + 1] in _TEST_RUNNER_MODULES
    return False


def testwrite_targets_bash(command: str, cwd: str) -> list[tuple[Path, str]]:
    """Seam onto ``bash_writes``, minus the targets a test RUN merely names.

    A `touch` of a new test or a heredoc with a write verb still refuses.
    """
    reader = _module("bash_writes")
    grouped = reader.write_targets_by_segment(command, cwd)
    no_write = getattr(reader, _NO_WRITE_VERB_ATTR, "")
    pairs: list[tuple[Path, str]] = []
    for segment, hits in grouped:
        run = _is_test_run(segment)
        for target, why in hits:
            if run and _INTERPRETER_REASON in why:
                continue
            if no_write and no_write in why:
                continue
            pairs.append((target, why))
    return pairs


def _refuse_creation(targets: list[Path], policy: Any, branch: str, lane: str) -> dict:
    """Build the refusal for a blocked CREATION, naming the config and the cure."""
    named = "\n".join(f"  {t}" for t in targets)
    who = f"branch '{branch}'" if branch else "this session"
    reason = (
        f"New test file blocked ({lane}): agents do not create tests right now.\n"
        f"{named}\n\n"
        "The owner's ruling, 2026-09-01 (DPLAN-0323): self-directed test creation is off across "
        "the fleet while @seedgo's test_quality v5 pack lands. Editing an EXISTING test to fix "
        "a red is still allowed — this is about the corpus growing, not about freezing it.\n\n"
        f"Policy: {policy.path}\n"
        f'  to lift for one branch : add "{branch or "<branch>"}" to the "allow" array\n'
        '  to lift fleet-wide     : set "agent_test_writing" to "on"\n'
        f"  to read it here        : drone @hooks testwrite\n\n"
        f"This is a human ruling, not a lint — {who} cannot flip it. It is in the tier-1 navmap "
        "house rules, so it is not news: a needed test goes through @devpulse NAMING THE DEFECT OR "
        "CONTRACT IT PINS — that clause is the ask, not the mail.\n"
        '  drone @ai_mail email @devpulse "New test needed: <file>" "<the defect or contract it pins>"'
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
    """Apply the test-write policy and return a block or allow decision."""
    tool_name = hook_data.get("tool_name", "") if isinstance(hook_data, dict) else ""
    if tool_name != "Bash" and tool_name not in EDIT_TOOLS:
        return _ALLOW
    try:
        tool_input = hook_data.get("tool_input", {}) or {}
        cwd = hook_data.get("cwd", "") or os.getcwd()
        lane = "scripted" if tool_name == "Bash" else "tool"

        targets = _module("testwrite_targets")
        created, edited = targets.classify(_targets(tool_name, tool_input, cwd))
        if not created and not edited:
            # Policy deliberately unread here: a broken policy file must not reach ordinary work.
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
                # The ruling only ever blocked creation; refusing an edit here would extend it by accident.
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

    except Exception as exc:  # fail closed on the write this gate guards
        logger.error("[HOOKS] testwrite_gate: crashed on %s, refusing it: %s", tool_name, exc)
        return _block(GATE_CRASHED.format(error=f"{type(exc).__name__}: {exc}"))


# Template pointer, @seedgo's contract: on PostToolUse in tests/**, one line pointing at the LOCAL page, read per call.

#: The page @seedgo stamps into each branch's tests/, and the receipt beside it.
TEMPLATE_PAGE = "TEST_TEMPLATE.md"
TEMPLATE_RECEIPT = ".template_version.json"

_TEMPLATE_KEY = "test_template"

#: The page decides whether the line appears; an unreadable receipt costs only the version word.
_DEFAULT_VERSION = "v1"


def _nearest_test_tree(path: Path) -> Path | None:
    """The innermost ``tests`` directory *path* sits in, or None."""
    for parent in path.parents:
        if parent.name == targets_module_test_dir():
            return parent
    return None


def targets_module_test_dir() -> str:
    """The directory name that marks a test tree, read from the classifier."""
    try:
        return str(_module("testwrite_targets").TEST_DIR)
    except Exception as exc:
        logger.info("[HOOKS] testwrite_gate: classifier unread for TEST_DIR (%s)", exc)
        return "tests"


def _template_version(tests_dir: Path) -> str:
    """The template version the local receipt names, as ``v<major>``."""
    receipt = tests_dir / TEMPLATE_RECEIPT
    try:
        data = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # Only reached when the PAGE exists, so a missing receipt is a half-landed stamp.
        logger.info("[HOOKS] testwrite_gate: template receipt unread at %s (%s)", receipt, exc)
        return _DEFAULT_VERSION
    version = (data.get("template_versions") or {}).get(_TEMPLATE_KEY) if isinstance(data, dict) else None
    if not isinstance(version, str) or not version:
        return _DEFAULT_VERSION
    return f"v{version.split('.')[0]}"


def _spelled(path: Path, cwd: str) -> str:
    """*path* as a line can carry it: project-relative when it is inside one."""
    try:
        project = _module("write_ownership").project_of(Path(cwd))
        if project is not None:
            return path.resolve().relative_to(project.root).as_posix()
    except Exception as exc:
        logger.info("[HOOKS] testwrite_gate: no project root for %s (%s) — absolute path", path, exc)
    return path.as_posix()


def template_pointer(hook_data: dict) -> dict:
    """PostToolUse: one line pointing at the branch's own test template page.

    Suppressed when the branch carries no page (unstamped). Never raises.
    """
    try:
        tool_name = hook_data.get("tool_name", "")
        if tool_name != "Bash" and tool_name not in EDIT_TOOLS:
            return _ALLOW

        tool_input = hook_data.get("tool_input", {}) or {}
        cwd = hook_data.get("cwd", "") or os.getcwd()
        in_tree = _module("testwrite_targets").in_test_tree

        touched = next((t for t in _targets(tool_name, tool_input, cwd) if in_tree(t)), None)
        if touched is None:
            return _ALLOW

        tests_dir = _nearest_test_tree(touched)
        if tests_dir is None:
            return _ALLOW

        page = tests_dir / TEMPLATE_PAGE
        if not page.exists():
            logger.info(
                "[HOOKS] testwrite_gate: template pointer suppressed — no page at %s (branch unstamped)",
                page,
            )
            return _ALLOW

        line = (
            f"Test template {_template_version(tests_dir)}: {_spelled(page, cwd)}"
            f" - then drone @seedgo checklist {_spelled(touched, cwd)}"
        )
        logger.info("[HOOKS] testwrite_gate: template pointer injected for %s", touched)
        document = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": line,
            }
        }
        return {"stdout": json.dumps(document), "exit_code": 0}

    except Exception as exc:
        # A pointer is a courtesy, never a wall: a defect costs the line and nothing else.
        logger.error("[HOOKS] testwrite_gate: template pointer failed (silent): %s", exc)
        return _ALLOW
