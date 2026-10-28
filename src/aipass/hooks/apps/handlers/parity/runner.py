# =================== AIPass ====================
# Name: runner.py
# Version: 1.2.0
# Description: Provider parity: the same scripted prompts headless on Claude, Codex and OpenCode, hook by hook
# Branch: hooks
# Layer: apps/handlers/parity
# Created: 2026-10-26
# Modified: 2026-10-28
# =============================================

"""Provider parity runner.

Each lane is one scripted prompt, sent the same on every provider from the branch's cwd. The oracle is
engine.jsonl: every per-hook line carries the payload's session_id, so a session's hook record is read
back by the id each CLI prints. A row reads one hook's record in that session and the two readings are
compared; an accepted difference is marked, not counted. OpenCode runs on a free model: a free-limit
answer reruns the lane once on the next model, never in a loop.
"""

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from aipass.hooks.apps.handlers.config import diagnostics
from aipass.hooks.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger

PROVIDERS = ("claude", "codex", "opencode")
DEFAULT_PROVIDERS = ("claude", "codex")
OPENCODE_MODELS = ("opencode/deepseek-v4.1-flash-free", "opencode/nemotron-3.5-lightning-free")
FREE_LIMIT = "provider.free-limit"
RUN_TIMEOUT = 600

SAME, ACCEPTED, DIFFERENT, NO_DATA, NOT_COMPARED = "same", "accepted", "DIFFERENT", "no data", "not compared"
FAILING = (DIFFERENT, NO_DATA)

PREFIX = (
    "This is an authorized AIPass hooks parity test. Do exactly the steps below, once each, in order. "
    "When a hook or gate refuses a step, do not retry it and do not work around it; go to the next step. "
    "Do not run your startup protocol unless a step asks for it. Finish with a one-line summary.\n"
)
HELLO = PREFIX + "1. Reply with the word OK. Run no tools."
OVER_CAP = "parity probe " + "x" * 137


@dataclass(frozen=True)
class Row:
    lane: str
    label: str
    event: str
    hook: str
    kind: str  # inject | ran | refused | pointer
    accepted: str = ""


_PROMPT_HOOKS = (
    "presence_gate",
    "persistent_alert",
    "tier0_kernel",
    "navmap",
    "branch_prompt",
    "identity_injector",
    "email_notification",
    "compass_recall",
    "feedback_pulse",
    "auto_process",
    "context_gauge",
    "temporal",
)

ROWS = (
    *(Row("A", f"prompt: {h}", "UserPromptSubmit", h, "inject") for h in _PROMPT_HOOKS),
    Row("B", "start: cadence_reset", "SessionStart", "cadence_reset", "ran"),
    Row("B", "start: release_notice", "SessionStart", "release_notice", "ran"),
    Row("B", "start: session_pointer", "SessionStart", "session_pointer", "ran"),
    Row("B", "start: culture", "SessionStart", "culture", "ran", "native on Claude, a SessionStart row on Codex"),
    Row("B", "pointer file (headless: untouched)", "", "", "pointer"),
    Row("C", "cross-branch write", "PreToolUse", "pre_edit_gate", "refused"),
    Row("C", "raw git status", "PreToolUse", "git_gate", "refused"),
    Row("C", "raw rm", "PreToolUse", "rm_gate", "refused"),
    Row("C", "new test file", "PreToolUse", "testwrite_gate", "refused"),
    Row("D", "edit gate on own file", "PreToolUse", "pre_edit_gate", "refused"),
    *(
        Row("D", f"post: {h}", "PostToolUse", h, "ran")
        for h in ("auto_fix_diagnostics", "comment_budget", "trinity_tripwire", "post_compact_regrounding")
    ),
    Row("E", "stop: presence_release", "Stop", "presence_release", "ran"),
    Row("E", "stop: stop_sound", "Stop", "stop_sound", "ran"),
    Row("E", "subagent stop", "SubagentStop", "subagent_stop_gate", "ran", "the sub-agent mechanism differs"),
    Row("F", "over-cap .trinity edit", "PreToolUse", "pre_edit_gate", "refused"),
    Row("F", "pre: trinity_tripwire_snapshot", "PreToolUse", "trinity_tripwire_snapshot", "ran"),
    Row("F", "post: trinity_tripwire", "PostToolUse", "trinity_tripwire", "ran"),
)

LANES = ("A", "B", "C", "D", "E", "F")


def lane_prompt(lane: str, branch: Path, other: Path) -> str:
    """The one prompt a lane sends to both providers; A and B share a session. *other* is a sibling branch."""
    if lane in ("A", "B"):
        return HELLO
    if lane == "C":
        probe = Path(tempfile.gettempdir()) / "parity_probe_rm.txt"
        return PREFIX + (
            f"1. Create the file {other / 'parity_probe.txt'} containing the word probe.\n"
            "2. Run the shell command `git status`.\n"
            f"3. Run the shell command `touch {probe} && rm {probe}`.\n"
            "4. Create the file tests/test_parity_probe.py containing `def test_probe(): pass`."
        )
    if lane == "D":
        return PREFIX + (
            "1. Create the file docs.local/parity_probe.md containing the line `probe one`.\n"
            "2. Change that line to `probe two`."
        )
    if lane == "E":
        return PREFIX + "1. Start one sub-agent with the task: reply with the word OK. Wait for it.\n2. Reply DONE."
    if lane == "F":
        return PREFIX + (
            "1. Read .trinity/passport.json, then .trinity/local.json, then .trinity/observations.json, "
            "one file per tool call.\n"
            f"2. Run `drone @prax dashboard refresh @{branch.name}`.\n"
            "3. Using your file edit tool, once, add one entry to the todos list in .trinity/local.json "
            f"whose task is exactly: {OVER_CAP}"
        )
    raise ValueError(f"unknown lane {lane}")


def launch_argv(provider: str, model: str = "") -> list[str]:
    """The headless launch; the prompt goes on stdin for all (the edit gate refuses a long argv prompt).

    OpenCode mints its own session id: one of ours is refused by the free tier as a false 429."""
    if provider == "opencode":
        binary = shutil.which("opencode") or str(Path.home() / ".opencode" / "bin" / "opencode")
        return [binary, "run", "--standalone", "--format", "json", "--auto", "-m", model or OPENCODE_MODELS[0]]
    if provider == "claude":
        return ["claude", "-p", "--model", model or "sonnet", "--permission-mode", "bypassPermissions"] + [
            "--output-format",
            "json",
        ]
    return [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        *(["-m", model] if model else []),
        "-",
    ]


def launch_env(branch: Path) -> dict:
    """dispatch_monitor's headless env: dispatched, no inherited CLI session, PWD at the branch."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "CODEX"))}
    for key in ("AIPASS_CALLER_BRANCH", "AIPASS_CALLER_CWD", "AIPASS_BOT_ID", "OPENCODE_SESSION_ID"):
        env.pop(key, None)
    env["AIPASS_SESSION_TYPE"] = "dispatched"
    # OpenCode takes its directory from $PWD before its real cwd.
    env["PWD"] = str(branch)
    return env


def session_id_of(provider: str, stdout: str) -> str:
    """Claude's result JSON names the session; Codex's first --json event names the thread; OpenCode's every line."""
    for line in stdout.splitlines():
        try:
            doc = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.debug("[HOOKS] parity: %s printed a non-JSON line: %s", provider, exc)
            continue
        if not isinstance(doc, dict):
            continue
        if provider == "claude" and doc.get("session_id"):
            return str(doc["session_id"])
        if provider == "codex" and doc.get("type") == "thread.started":
            return str(doc.get("thread_id", ""))
        if provider == "opencode" and doc.get("sessionID"):
            return str(doc["sessionID"])
    return ""


def session_entries(session_id: str) -> list[dict]:
    """Every per-hook engine line for the session, both log generations."""
    log = Path(diagnostics.LOG_FILE)
    entries = []
    for path in (log.with_name(log.name + ".1"), log):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.info("[HOOKS] parity: %s unreadable: %s", path, exc)
            continue
        for line in lines:
            try:
                doc = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.debug("[HOOKS] parity: torn line in %s: %s", path, exc)
                continue
            if isinstance(doc, dict) and doc.get("session_id") == session_id and "exit_code" in doc:
                entries.append(doc)
    return entries


def observe(row: Row, entries: list[dict], pointer_moved: bool) -> str:
    """What one row saw in one session."""
    if row.kind == "pointer":
        return "written" if pointer_moved else "untouched"
    mine = [e for e in entries if e.get("event") == row.event and e.get("hook") == row.hook]
    if not mine:
        return "not reached"
    if row.kind == "refused":
        return "refused" if any(e.get("exit_code") == 2 for e in mine) else "not refused"
    if row.kind == "inject":
        return "injected" if any(e.get("stdout_len", 0) > 0 for e in mine) else "silent"
    return "ran"


def verdict(row: Row, readings: dict) -> str:
    """same / accepted / DIFFERENT across the providers run, or no data when a session left no record."""
    if len(readings) < 2:
        return NOT_COMPARED
    if any(value == NO_DATA for value in readings.values()):
        return NO_DATA
    if len(set(readings.values())) == 1:
        return SAME
    return ACCEPTED if row.accepted else DIFFERENT


def free_limited(stdout: str) -> bool:
    """True when an OpenCode stream carries the free tier's usage-limit error."""
    for line in stdout.splitlines():
        try:
            doc = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.debug("[HOOKS] parity: opencode printed a non-JSON line: %s", exc)
            continue
        error = doc.get("error") if isinstance(doc, dict) else None
        if isinstance(error, dict) and error.get("type") == FREE_LIMIT:
            return True
    return False


def _pointer_stamp(branch: Path) -> float:
    try:
        return (branch / ".ai_mail.local" / "session.json").stat().st_mtime
    except OSError:
        return 0.0


def run_session(provider: str, prompt: str, branch: Path) -> tuple[str, list[dict], bool]:
    """One headless session: its id, its hook record, whether it moved the session pointer."""
    before = _pointer_stamp(branch)
    for model in OPENCODE_MODELS if provider == "opencode" else ("",):
        try:
            done = subprocess.run(
                launch_argv(provider, model),
                input=prompt,
                cwd=str(branch),
                env=launch_env(branch),
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("[HOOKS] parity: %s session did not finish: %s", provider, exc)
            return "", [], False
        if not free_limited(done.stdout):
            break
        logger.warning("[HOOKS] parity: %s answered the free limit (429)", model)
    else:
        return "", [], False
    session_id = session_id_of(provider, done.stdout)
    json_handler.log_operation(
        "parity_session", {"provider": provider, "model": model, "session": session_id, "exit": done.returncode}
    )
    if not session_id:
        logger.warning("[HOOKS] parity: %s printed no session id (exit %s)", provider, done.returncode)
        return "", [], False
    return session_id, session_entries(session_id), _pointer_stamp(branch) != before


def send_probe_mail(branch: Path) -> str:
    """Lane A's one unread mail; it stays in the target's inbox, which only the target can close."""
    argv = ["drone", "@ai_mail", "email", f"@{branch.name}", "Parity probe (no action)", "Close me: hooks parity."]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("[HOOKS] parity: probe mail not sent: %s", exc)
        return f"not sent: {exc}"
    return "sent" if done.returncode == 0 else f"not sent: {(done.stdout + done.stderr).strip()[:120]}"
