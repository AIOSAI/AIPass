# =================== AIPass ====================
# Name: codex.py
# Version: 2.8.0
# Description: Codex bridge — mounts the promoted hook code, maps apply_patch, fails closed on PreToolUse
# Branch: hooks
# Layer: apps/handlers/bridges
# Created: 2026-07-10
# Modified: 2026-11-17
# =============================================

"""Codex bridge.

Called from Codex's user-level hooks.json ($CODEX_HOME or ~/.codex), which the provider wire writes
from the manifest's cli.codex rows.
Codex speaks Claude's hook protocol and names its shell tool Bash; its file tool is apply_patch, one
patch over many files, so each file becomes the Claude call the gates judge (Write, MultiEdit, a
shell delete or move) and the first refusal answers for the whole patch. Codex blocks by
permissionDecision, not exit code 2. The hook code is the promoted copy (mount.py); a PreToolUse
call whose hook code cannot load, raises, or exits 2 is DENIED.
"""

import contextlib
import importlib.util
import json
import os
import shlex
import sys
import time

GUARDED_EVENTS = frozenset({"PreToolUse"})

PATCH_TOOL = "apply_patch"

PROVIDER = "codex"

SESSION_ENV = "CLAUDE_CODE_SESSION_ID"

ADD, UPDATE, DELETE = "*** Add File: ", "*** Update File: ", "*** Delete File: "
MOVE = "*** Move to: "

UNJUDGED = (
    "apply_patch names no file the gates can judge, so it does not run. "
    "Name each file in an *** Add File:, *** Update File: or *** Delete File: header."
)

BROKEN = (
    "HOOKS BROKEN: the AIPass hook engine could not run ({error}).\n"
    "Every gate it runs is down, so nothing they guard runs until it is fixed.\n"
    'Mail @hooks and @devpulse: drone @ai_mail email @hooks "Hooks broken" "<what you ran, and this text>"'
)


#: Where a break is recorded: @trigger's branch watcher reads src/aipass/*/logs/*.log for ERROR lines.
BREAK_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "logs", "bridge.log")
LIVE_BREAK_LOG = BREAK_LOG


def _log(level: str, message: str, *args: object) -> None:
    """Log through prax. Imported per call, inside main's try: a prax that cannot load is a broken engine (_broken)."""
    from aipass.prax import logger

    getattr(logger, level)(message, *args)


def _normalize_stdin(stdin_data: str) -> str:
    """Remap Codex field names to engine-expected names, and name the provider (a payload without one is Claude's)."""
    if not stdin_data.strip():
        return stdin_data
    try:
        parsed = json.loads(stdin_data)
        if not isinstance(parsed, dict):
            return stdin_data
        if "input" in parsed and "tool_input" not in parsed:
            parsed["tool_input"] = parsed.pop("input")
        parsed.setdefault("provider", PROVIDER)
        return json.dumps(parsed)
    except (json.JSONDecodeError, TypeError) as exc:
        _log("info", "[HOOKS:codex] stdin normalization failed: %s", exc)
        return stdin_data


def _as_object(text: str) -> dict | None:
    """*text* as a JSON object, or None when it is plain text."""
    try:
        doc = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return doc if isinstance(doc, dict) else None


def _wrap_output(event_type: str, output: str, exit_code: int) -> str:
    """The engine's answer as the one JSON document Codex reads.

    Exit 2 on a guarded event is a deny whatever the text: Claude Code refuses on any exit 2, and so must this.
    A JSON answer is already Claude's protocol, which Codex reads; plain text is context.
    """
    doc = _as_object(output)
    if exit_code == 2 and event_type in GUARDED_EVENTS:
        reason = (doc.get("reason") if doc is not None else output.strip()) or "Blocked by AIPass hook"
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event_type,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                },
                "systemMessage": reason,
            }
        )
    own = doc.get("hookSpecificOutput") if doc is not None else None
    if (
        doc is not None
        and event_type in GUARDED_EVENTS
        and isinstance(own, dict)
        and own.get("permissionDecision") == "ask"
    ):
        # Codex cannot ask: it marks the hook failed and runs the call, so an ask is a deny here.
        own["permissionDecision"] = "deny"
        doc.setdefault("systemMessage", own.get("permissionDecisionReason") or "Blocked by AIPass hook")
    if doc is not None:
        return json.dumps(doc)
    if not output:
        return json.dumps({})
    return json.dumps({"hookSpecificOutput": {"hookEventName": event_type, "additionalContext": output}})


def _patch_files(patch: str) -> list[dict]:
    """An apply_patch body split per file: its header, path, Move to destination and body lines."""
    files: list[dict] = []
    for line in patch.splitlines():
        header = next((h for h in (ADD, UPDATE, DELETE) if line.startswith(h)), None)
        if header:
            files.append({"op": header, "path": line[len(header) :].strip(), "move": "", "lines": []})
        elif files and line.startswith(MOVE):
            files[-1]["move"] = line[len(MOVE) :].strip()
        elif files and not line.startswith("*** "):
            files[-1]["lines"].append(line)
    return files


def _hunk_edits(lines: list[str]) -> list[dict]:
    """One MultiEdit edit per @@ hunk: context and - lines are the old text, context and + lines the new."""
    edits: list[dict] = []
    old: list[str] = []
    new: list[str] = []
    for line in [*lines, "@@"]:
        if line.startswith("@@"):
            if old or new:
                edits.append({"old_string": "\n".join(old), "new_string": "\n".join(new)})
            old, new = [], []
            continue
        mark, text = line[:1], line[1:]
        if mark != "+":
            old.append(text)
        if mark != "-":
            new.append(text)
    return edits


def _patch_calls(patch: str, cwd: str) -> list[tuple[str, dict]]:
    """The Claude calls a patch amounts to, one or two per file, in patch order."""
    calls: list[tuple[str, dict]] = []
    for entry in _patch_files(patch):
        path = os.path.join(cwd, entry["path"])
        if entry["op"] == ADD:
            content = "".join(line[1:] + "\n" for line in entry["lines"])
            calls.append(("Write", {"file_path": path, "content": content}))
        elif entry["op"] == DELETE:
            calls.append(("Bash", {"command": " ".join(["rm", "--", shlex.quote(path)])}))
        else:
            calls.append(("MultiEdit", {"file_path": path, "edits": _hunk_edits(entry["lines"])}))
            if entry["move"]:
                dest = os.path.join(cwd, entry["move"])
                calls.append(("Bash", {"command": " ".join(["mv", "--", shlex.quote(path), shlex.quote(dest)])}))
    return calls


def _claude_payloads(stdin_data: str) -> list[str]:
    """The payloads the engine runs: the one Codex sent, or one per call an apply_patch amounts to.

    A patch that names no file amounts to no call: an empty list.
    """
    normalized = _normalize_stdin(stdin_data)
    payload = _as_object(normalized)
    if payload is None or payload.get("tool_name") != PATCH_TOOL:
        return [normalized]
    tool_input = payload.get("tool_input")
    patch = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    calls = _patch_calls(str(patch), str(payload.get("cwd") or os.getcwd()))
    return [json.dumps({**payload, "tool_name": name, "tool_input": call}) for name, call in calls]


def _run_calls(arg: str, stdin_data: str) -> tuple[str, int]:
    """Run the engine once per payload; the first exit 2 answers for the whole tool call.

    No payload is a patch naming no file: a guarded event denies it with the reason, a caller's
    mistake at WARNING, not a broken engine.
    """
    from aipass.hooks.apps.handlers.config.output_merge import combine_outputs
    from aipass.hooks.apps.modules.engine import run_event

    event_type = arg.split(":", 1)[0]
    payloads = _claude_payloads(stdin_data)
    if not payloads and event_type in GUARDED_EVENTS:
        _log("warning", "[HOOKS:codex] apply_patch denied on %s: %s", event_type, UNJUDGED)
        return json.dumps({"decision": "block", "reason": UNJUDGED}), 2
    outputs: list[tuple[str, str, str]] = []
    for payload in payloads:
        output, exit_code = run_event(arg, payload)
        if exit_code == 2:
            return output, exit_code
        if output:
            outputs.append((str(len(outputs)), "", output))
    return combine_outputs(event_type, outputs), 0


def _mount() -> str:
    """Serve aipass.hooks.apps from the promoted copy; on a bad copy, from the source tree, loudly."""
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("_aipass_hooks_mount", os.path.join(here, "mount.py"))
    if spec is None or spec.loader is None:
        raise ImportError("mount.py has no import spec")
    mount = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mount)
    return mount.mount_or_source(__file__, "codex")


def _reason(exc: BaseException) -> str:
    """The BROKEN text for *exc*; one whose message itself raises is named by its type, and still denied."""
    try:
        return BROKEN.format(error=f"{type(exc).__name__}: {exc}")
    except Exception:
        return BROKEN.format(error=f"{type(exc).__name__}, whose message could not be read")


def _record_break(event_type: str, line: str) -> None:
    """Append one ERROR line in prax's format, after the answer has left: an attempt, never a wait."""
    if "_pytest" in sys.modules and BREAK_LOG == LIVE_BREAK_LOG:
        return  # prax's own test seam: a suite run's break never lands in the live log medic reads
    try:
        entry = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | bridges.codex | ERROR | {line} on {event_type}\n"
        fd = os.open(BREAK_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK, 0o666)
        try:
            os.write(fd, entry.encode("utf-8", "backslashreplace"))
        finally:
            os.close(fd)
    except BaseException as exc:  # the answer is already out: nothing the record raises may change it
        with contextlib.suppress(BaseException):
            sys.stderr.write(
                f"[HOOKS:codex] bridge: the break was not recorded in {BREAK_LOG}: {type(exc).__name__}: {exc}\n"
            )


def _broken(event_type: str, exc: BaseException) -> None:
    """Deny a guarded event outright; any other event gets an empty document. Answer first, record after.

    Codex reads the answer from stdout alone, so it is written and flushed before anything else runs.
    """
    reason = _reason(exc)
    answer = json.dumps({})
    if event_type in GUARDED_EVENTS:
        answer = _wrap_output(event_type, json.dumps({"decision": "block", "reason": reason}), 2)
    sys.stdout.write(answer)
    sys.stdout.flush()
    with contextlib.suppress(BaseException):
        sys.stderr.write(reason.encode("utf-8", "backslashreplace").decode("utf-8") + "\n")
    _record_break(event_type, reason.splitlines()[0])


def main() -> None:
    """Entry point — receive event type from Codex, dispatch via the promoted engine."""
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: codex.py <EventType> or codex.py <EventType:hook_name>\n")
        sys.exit(1)

    arg = sys.argv[1]
    event_type = arg.split(":", 1)[0]

    try:
        stdin_data = "" if sys.stdin.isatty() else sys.stdin.read()
        payload = _as_object(stdin_data)
        if payload is not None and payload.get("session_id"):
            # Cadence and the ledgers key a seat on this variable; a Codex hook inherits none, or its launcher's.
            os.environ[SESSION_ENV] = str(payload["session_id"])
        _mount()
        from aipass.hooks.apps.handlers.json import json_handler

        output, exit_code = _run_calls(arg, stdin_data)
        json_handler.log_operation("bridge", {"event": arg, "exit_code": exit_code})
    except BaseException as exc:  # fail closed on the guarded event, however it broke: see _broken
        _broken(event_type, exc)
        return

    sys.stdout.write(_wrap_output(event_type, output, exit_code))


if __name__ == "__main__":
    main()
