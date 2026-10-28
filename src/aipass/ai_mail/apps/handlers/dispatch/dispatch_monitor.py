# =================== AIPass ====================
# Name: dispatch_monitor.py
# Description: Agent Lifecycle Monitor
# Version: 2.13.0
# Created: 2026-03-02
# Modified: 2026-10-28
# =============================================

"""
Agent Lifecycle Monitor

Spawned by wake.py in place of claude; the lock PID is this monitor, alive as long as claude is.
Reference: docs/wake_pipeline.md
"""

import json
import os
import shlex
import socket
import sys
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.dispatch import register, session_pointer
from aipass.ai_mail.apps.handlers.dispatch import report as report_mod
from aipass.ai_mail.apps.handlers.paths import find_project_root
from aipass.ai_mail.apps.handlers.registry.read import RegistryUnreadable, get_caller_project_branches

STARTUP_TIMEOUT = 90
RATE_LIMIT_DELAY = 30
HARD_TIMEOUT = 7200  # 2 hours
POLL_INTERVAL = 5


def is_sandbox_enabled() -> bool:
    """Check if dispatch sandbox is enabled via AIPASS_SANDBOX_ENABLED env var.

    A door: main() reads it once per dispatch; the env var is the deployment's switch.
    """
    return os.environ.get("AIPASS_SANDBOX_ENABLED", "").lower() in ("1", "true", "yes")


def wrap_for_sandbox(cmd: list, branch_path: Path) -> list:
    """Wrap a claude command in the srt kernel sandbox.

    A door: main() calls it when the sandbox flag is on; @hooks owns the building blocks it calls.
    Raises on ANY failure — caller must not silently fall back to unsandboxed.
    """
    from aipass.hooks.apps.modules.sandbox import build_policy, build_srt_config, resolve_bwrap_command

    policy = build_policy(branch_path)
    srt_config = build_srt_config(policy)
    cmd_str = shlex.join(cmd)
    bwrap_cmd = resolve_bwrap_command(cmd_str, srt_config)
    return ["/bin/bash", "-c", bwrap_cmd]


def _connect_broker(repo_root: Path, branch_name: str) -> socket.socket:
    """Create an identified broker connection for the target branch.

    Raises on ANY failure — caller must not silently skip the broker.
    """
    from aipass.drone.apps.modules.door_broker import create_identified_connection

    socket_path = repo_root / ".ai_central" / "drone_broker.sock"
    secret_path = repo_root / ".ai_central" / "broker_secret"
    return create_identified_connection(socket_path, secret_path, branch_name)


MAX_WAKE_DEPTH = 3

# argv, not env: the monitor's env becomes the agent's and would leak into its own dispatches.
NO_WAKE_BACK_FLAG = "--no-wake-back"
# `--provider=codex` before "--" picks the codex probe, parser and retry shape; absent means claude.
PROVIDER_FLAG_PREFIX = "--provider="
# `--opencode-config=<json>` before "--": the caller's OpenCode config, set in the child env after the strip.
OPENCODE_CONFIG_FLAG_PREFIX = "--opencode-config="
OPENCODE_CONFIG_ENV = "OPENCODE_CONFIG_CONTENT"
CODEX = session_pointer.CODEX
# Exit 0 whose stream shows an `error` event or no `turn.completed`: a failed Codex turn.
CODEX_STREAM_FAILED = -5
OPENCODE = session_pointer.OPENCODE
# Exit 0 whose stream carries no `text` part: an OpenCode run that never answered.
OPENCODE_STREAM_FAILED = -6
# The providers whose stdout streams live: startup is the first stdout byte, not a JSONL transcript.
STREAMING_PROVIDERS = (CODEX, OPENCODE)
WAKE_RESULT_DECLINED = "declined"


def wake_sender(sender: str, branch_email: str, exit_code: int, target_home: Optional[Path] = None) -> str:
    """Wake the dispatcher back after target completion.

    A door: main() calls it, and its tags are read in dispatch_wake.log and by managers.

    Managers are never woken; they are MAILED instead, here (wake_branch's manager gate sends nothing).
    Returns a dispatch_wake.log tag; never called under --no-wake-back.
    """
    if not sender or not sender.strip():
        logger.info("[monitor] Wake-back skipped — no sender")
        return "skipped_sender"

    normalized_sender = f"@{sender.lstrip('@').lower()}"
    normalized_target = f"@{branch_email.lstrip('@').lower()}"
    if normalized_sender == normalized_target:
        logger.info("[monitor] Wake-back skipped — sender %s is the completed agent (self-wake)", sender)
        return "skipped_self"

    depth = int(os.environ.get("AIPASS_WAKE_DEPTH", "0"))
    if depth >= MAX_WAKE_DEPTH:
        logger.warning("[monitor] Wake-back skipped — depth %d >= max %d", depth, MAX_WAKE_DEPTH)
        return "blocked_depth"

    try:
        from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

        os.environ["AIPASS_WAKE_DEPTH"] = str(depth + 1)
        # sender="" ends the wake-back chain. The message names the target: an empty inbox is normal here.
        wake_back_message = (
            f"{branch_email} finished (exit {exit_code}). Check its reply in your inbox, "
            "verify what it did, and continue."
        )
        wake_status, success = wake_branch(sender, custom_message=wake_back_message, auto=True, sender="")

        # Before the success check: the manager gate returns True having woken nothing.
        manager_step = wake_status.find_step("manager")
        if manager_step and manager_step[0] == "info":
            # The wake is refused; the notification is not optional.
            if _mail_wake_back(sender, branch_email, exit_code, target_home):
                return "mailed_manager"
            return "failed_manager_mail"

        if success:
            logger.info("[monitor] Wake-back: %s woken after %s completed (exit %d)", sender, branch_email, exit_code)
            return "success"

        summary = wake_status.summary
        lower = summary.lower()
        if "interactive" in lower or "occupancy" in lower or "occupied" in lower:
            logger.info("[monitor] Wake-back blocked — sender %s has interactive session: %s", sender, summary)
            return "blocked_occupied"
        if "active agent" in lower or "lock" in lower:
            logger.info("[monitor] Wake-back blocked — sender %s has active lock: %s", sender, summary)
            return "blocked_locked"

        logger.info("[monitor] Wake-back: %s not woken — %s", sender, summary)
        return "failed"
    except Exception as e:
        logger.warning("[monitor] Wake-back failed for %s: %s", sender, e)
        return "failed"


_AI_MAIL_DIR = Path(__file__).resolve().parents[3]  # ai_mail/


def _sending_home(recipient: str, target_home: Optional[Path]) -> Path:
    """Where a monitor notice is sent from: ai_mail's home, unless that crosses the project fence.

    A manager in another (non-AIPass) project is mailed from the woken branch's home, or the fence refuses it.
    """
    if target_home is None:
        return _AI_MAIL_DIR
    target_root = find_project_root(target_home)
    if target_root is None or target_root == find_project_root(_AI_MAIL_DIR):
        return _AI_MAIL_DIR
    try:
        project_branches = get_caller_project_branches(str(target_home))
    except RegistryUnreadable as e:
        logger.warning(
            "[monitor] %s's project registry unreadable, notice to %s sent from ai_mail: %s", target_home, recipient, e
        )
        return _AI_MAIL_DIR
    if recipient.strip().lower() in {k.lower() for k in project_branches}:
        return target_home
    return _AI_MAIL_DIR


def _send_from_ai_mail(
    recipient: str, subject: str, body: str, target_home: Optional[Path]
) -> subprocess.CompletedProcess:
    """Send one of the monitor's notices through drone, as @ai_mail.

    ai_mail's home as cwd and its name in the env, so drone sees one identity claim.
    _sending_home's cross-project exception still logs an identity conflict.
    """
    env = dict(os.environ)
    env["AIPASS_BRANCH_NAME"] = "ai_mail"
    return subprocess.run(
        ["drone", "@ai_mail", "send", recipient, subject, body],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(_sending_home(recipient, target_home)),
        env=env,
    )


def _mail_wake_back(sender: str, branch_email: str, exit_code: int, target_home: Optional[Path]) -> bool:
    """Deliver the wake-back as MAIL when the sender cannot be woken.

    Managers stay blocklisted from wakes: two claudes on one session id kill the running job.
    Sent through drone as @ai_mail; in-process sending has no sender identity.

    """
    subject = f"Dispatch complete: {branch_email} finished (exit {exit_code})"
    body = (
        f"{branch_email} finished (exit {exit_code}).\n\n"
        f"You are a manager, so no agent was woken — that is by design and not a "
        f"failure. This mail IS the wake-back.\n\n"
        f"Check {branch_email}'s reply in your inbox, verify what it did, and hand "
        f"off the next phase if there is one."
    )
    try:
        result = _send_from_ai_mail(sender, subject, body, target_home)
        if result.returncode != 0:
            logger.warning(
                "[monitor] Wake-back mail to manager %s FAILED (exit %d): %s",
                sender,
                result.returncode,
                (result.stderr or "").strip()[:200],
            )
            return False
        logger.info("[monitor] Wake-back mailed to manager %s (%s exit %d)", sender, branch_email, exit_code)
        return True
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("[monitor] Wake-back mail to manager %s failed: %s", sender, e)
        return False


def log_wake_result(branch_email: str, sender: str, exit_code: int, result: str, lock_file: str):
    """Append a wake-back result line to dispatch_wake.log under target's logs/.

    A door: main() calls it, and its line is read in dispatch_wake.log by managers and the register.
    """
    lock_path = Path(lock_file).resolve()
    logs_dir = lock_path.parent.parent / "logs"
    log_file = logs_dir / "dispatch_wake.log"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        line = (
            f"{time.strftime('%Y-%m-%dT%H:%M:%S')}"
            f" target={branch_email}"
            f" sender={sender}"
            f" exit_code={exit_code}"
            f" wake_result={result}\n"
        )
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        logger.info("[monitor] Failed to write dispatch_wake.log: %s", e)


def _send_bounce(branch_email: str, reason: str, sender: str, lock_file: str, stderr_log: str) -> bool:
    """Send return-to-sender bounce email via drone. True when drone accepted the mail."""
    subject = f"BOUNCE: Dispatch to {branch_email} failed"

    stderr_tail = ""
    try:
        with open(stderr_log, "r", encoding="utf-8") as f:
            lines = f.readlines()
        stderr_tail = "".join(lines[-20:]).strip()
    except (OSError, FileNotFoundError) as e:
        logger.warning("[monitor] Failed to read stderr log %s: %s", stderr_log, e)
        stderr_tail = "(no stderr captured)"

    body = (
        f"Agent at {branch_email} exited abnormally.\n\n"
        f"Reason: {reason}\n\n"
        f"Stderr (last 20 lines):\n{stderr_tail}\n\n"
        f"Lock file cleaned automatically.\n"
        f"Re-dispatch if task was not completed."
    )

    try:
        return _send_from_ai_mail(sender, subject, body, Path(lock_file).parent.parent).returncode == 0
    except (subprocess.SubprocessError, OSError) as e:
        # The caller warns; the transport error rides in the fallback file beside the lock.
        try:
            bounce_file = Path(lock_file).parent / "last_bounce.json"
            with open(bounce_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "branch": branch_email,
                        "reason": reason,
                        "sender": sender,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "stderr_tail": stderr_tail,
                        "error": str(e),
                    },
                    f,
                    indent=2,
                )
        except OSError:
            logger.info("[monitor] Failed to write bounce file fallback")
        return False


def _note_undelivered_bounce(delivered: bool, branch_email: str, reason: str, sender: str) -> bool:
    """Warn once when a bounce did not reach the sender; returns `delivered` for the status."""
    if not delivered:
        logger.warning(
            "[monitor] BOUNCE NOT DELIVERED for %s to %s: the sender was not told. Reason: %s",
            branch_email,
            sender,
            reason,
        )
    return delivered


def _read_agent_stderr(stderr_log: str) -> str:
    """Read the dispatch stderr log, excluding the monitor's own framing lines.

    Its "--- " lines embed PIDs: a PID like 14290 would read as an HTTP 429.
    """
    try:
        with open(stderr_log, "r", encoding="utf-8") as f:
            return "".join(line for line in f if not line.lstrip().startswith("---"))
    except OSError as e:
        logger.warning("[monitor] Failed reading stderr log %s: %s", stderr_log, e)
        return ""


def _check_rate_limited(stderr_log: str) -> bool:
    """Check if stderr indicates API rate limiting or overload."""
    content = _read_agent_stderr(stderr_log)
    lower = content.lower()
    return "rate_limit" in lower or "429" in content or "overloaded" in lower or "529" in content


RESUME_FLAGS = ("--resume", "-r")
SESSION_ID_FLAG = "--session-id"


def _has_resume(claude_cmd: list) -> bool:
    """True when the command continues an existing conversation.

    Must see --resume as well as -c, or a pointer-resumed run never gets its strike-3 fresh switch.
    """
    return "-c" in claude_cmd or any(flag in claude_cmd for flag in RESUME_FLAGS)


def _session_id_in(claude_cmd: list) -> Optional[str]:
    """Return the value passed to --session-id, or None when absent."""
    if SESSION_ID_FLAG not in claude_cmd:
        return None
    value_index = claude_cmd.index(SESSION_ID_FLAG) + 1
    if value_index >= len(claude_cmd):
        logger.warning("[monitor] %s passed with no value — treating as no session id", SESSION_ID_FLAG)
        return None
    return claude_cmd[value_index]


def _make_fresh_cmd(claude_cmd: list) -> list:
    """Strip every session binding so the command starts a brand-new session.

    Value flags go as a PAIR: a leftover bare uuid would reach the CLI as the prompt.
    """
    fresh = []
    skip_value = False
    for arg in claude_cmd:
        if skip_value:
            skip_value = False
            continue
        if arg == "-c":
            continue
        if arg in RESUME_FLAGS or arg == SESSION_ID_FLAG:
            skip_value = True
            continue
        fresh.append(arg)
    return fresh


def cmd_for_attempt(claude_cmd: list, attempt: int, branch_path: Path, provider: str = "claude") -> Tuple[list, str]:
    """Build the command for one attempt of the 3-strike loop. Returns (cmd, mode).

    A door: main() calls it per attempt; it keeps the --resume/--session-id shapes wake.py builds.

    The CLI refuses a reused --session-id, so each attempt is built for where the last left the session.
    Codex carries no session flags: attempts 1-2 re-run its argv, strike 3 drops `resume <id>`.
    OpenCode re-runs its argv; strike 3 of a resume drops `--session <id>` and OpenCode mints a new one.
    """
    if provider == OPENCODE:
        if SESSION_FLAG_OPENCODE not in claude_cmd:
            return list(claude_cmd), "fresh"
        if attempt < 3:
            return list(claude_cmd), "resume"
        at = claude_cmd.index(SESSION_FLAG_OPENCODE)
        return [*claude_cmd[:at], *claude_cmd[at + 2 :]], "fresh"
    if provider == CODEX:
        is_resume = claude_cmd[1:3] == ["exec", "resume"]
        if attempt < 3 or not is_resume:
            return list(claude_cmd), "resume" if is_resume else "fresh"
        return [claude_cmd[0], "exec", *claude_cmd[4:]], "fresh"

    has_resume = _has_resume(claude_cmd)
    session_id = _session_id_in(claude_cmd)
    default_mode = "resume" if has_resume else "fresh"

    if attempt == 1:
        return list(claude_cmd), default_mode

    if attempt == 2:
        # A transcript for our minted id means attempt 1 spent it: resume instead.
        stripped = _make_fresh_cmd(claude_cmd) if session_id else []
        spent: Optional[bool] = False
        if session_id and stripped:
            try:
                spent = _transcript_exists(branch_path, session_id)
            except OSError as e:
                # Unknown is neither spent nor free; a new id is right either way.
                logger.warning(
                    "[monitor] Attempt 2: cannot tell whether session %s exists (%s) — minting a new id", session_id, e
                )
                spent = None
        if spent is None:
            return _fresh_cmd_with_new_id(claude_cmd, branch_path)
        if spent:
            logger.info("[monitor] Attempt 2: session %s already exists — retrying as --resume", session_id)
            # wake.py's tested shape: `--resume <id>` right after the binary, never after `-p`.
            return [stripped[0], RESUME_FLAGS[0], session_id, *stripped[1:]], "resume"
        return list(claude_cmd), default_mode

    # Strike 3 mints a NEW id rather than dropping it, so the branch still points somewhere real.
    if not has_resume and session_id is None:
        return list(claude_cmd), "fresh"

    return _fresh_cmd_with_new_id(claude_cmd, branch_path)


def _fresh_cmd_with_new_id(claude_cmd: list, branch_path: Path) -> Tuple[list, str]:
    """Strip the session binding, mint a new id, and point the branch at it.

    A failed pointer write is logged and never costs the attempt.
    """
    fresh_cmd = _make_fresh_cmd(claude_cmd)
    new_id = session_pointer.mint_session_id()
    fresh_cmd += [SESSION_ID_FLAG, new_id]
    if not session_pointer.write_pointer(branch_path, new_id, "monitor-retry-fresh"):
        logger.warning("[monitor] Retry pointer write failed for %s — running fresh anyway", new_id)
    return fresh_cmd, "fresh"


SESSION_FLAG_OPENCODE = "--session"


def _transcript_exists(branch_path: Path, session_id: str) -> Optional[bool]:
    """Whether a transcript file exists for this session in this branch.

    None when the home cannot be named; OSError when unstattable. cmd_for_attempt mints a new id on both.
    """
    transcript = session_pointer.transcript_file(branch_path, session_id)
    if transcript is None:
        logger.warning("[monitor] No home to locate session %s's transcript — its state is unknown", session_id)
        return None

    return transcript.is_file()


def _aimed_at_a_session(claude_cmd: list) -> bool:
    """True when WE chose the session, rather than letting mtime choose it."""
    return _session_id_in(claude_cmd) is not None or any(flag in claude_cmd for flag in RESUME_FLAGS)


def reconcile_pointer(branch_path: Path, stdout_log: str, claude_cmd: list) -> None:
    """Record the session the CLI actually used, when it differs from the pointer.

    A door: main() calls it after a clean run; wake.py reads the pointer it writes.

    Only when we AIMED at a session: recording a bare -c landing would make a guess permanent.
    """
    if not _aimed_at_a_session(claude_cmd):
        logger.info(
            "[monitor] %s ran on -c — not adopting the landed session as a pointer (mtime is a guess)",
            branch_path,
        )
        return
    actual = _parse_result_json(stdout_log).get("session_id")
    if not isinstance(actual, str) or not actual.strip():
        return
    actual = actual.strip()
    pointer = session_pointer.read_pointer(branch_path)
    if pointer is not None and pointer.get("session_id") == actual:
        return
    if not session_pointer.write_pointer(branch_path, actual, "monitor-reconciled"):
        logger.warning("[monitor] Could not reconcile pointer for %s to session %s", branch_path, actual)


def parse_codex_stream(stdout_log: str) -> dict:
    """Read a `codex exec --json` stream: session_id, result, usage, error, succeeded.

    session_id is thread.started's thread_id; result the LAST agent_message (what -o writes);
    succeeded needs turn.completed and no `error` event. error is the first error line, verbatim.
    """
    parsed: dict = {"session_id": None, "result": "", "usage": None, "error": "", "succeeded": False}
    try:
        lines = Path(stdout_log).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        logger.info("[monitor] No codex stream to parse at %s: %s", stdout_log, e)
        return parsed
    completed = False
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as e:
            logger.info("[monitor] codex stream line is not JSON, skipped: %s", e)
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        item = event.get("item")
        if not isinstance(item, dict):
            item = {}
        if kind == "thread.started" and parsed["session_id"] is None:
            parsed["session_id"] = event.get("thread_id")
        elif kind == "item.completed" and item.get("type") == "agent_message":
            parsed["result"] = str(item.get("text", ""))
        elif kind == "turn.completed":
            completed = True
            parsed["usage"] = event.get("usage")
        elif kind == "error" and not parsed["error"]:
            parsed["error"] = line.strip()
    parsed["succeeded"] = completed and not parsed["error"]
    return parsed


def reconcile_codex_pointer(branch_path: Path, stdout_log: str) -> None:
    """Point the branch at the thread Codex ran: it minted the id, so the stream is a fact, not a guess."""
    thread_id = parse_codex_stream(stdout_log)["session_id"]
    if not isinstance(thread_id, str) or not thread_id.strip():
        logger.warning("[monitor] codex stream for %s carried no thread.started — pointer unchanged", branch_path)
        return
    if not session_pointer.write_pointer(branch_path, thread_id.strip(), "monitor-codex", provider=CODEX):
        logger.warning("[monitor] Could not record codex thread %s for %s", thread_id, branch_path)


def parse_opencode_stream(stdout_log: str) -> dict:
    """Read an `opencode run --format json` stream: session_id, result, usage, cost, error, rate limit, succeeded.

    result is the LAST `text` part; usage and total_cost_usd sum every step_finish. error is the first
    `error` event's line, verbatim; succeeded needs a text part and no error. The stream has no closer.
    """
    parsed: dict = {
        "session_id": None,
        "result": "",
        "usage": None,
        "total_cost_usd": None,
        "num_turns": 0,
        "error": "",
        "rate_limited": False,
        "retry_after_s": None,
        "succeeded": False,
    }
    try:
        lines = Path(stdout_log).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        logger.info("[monitor] No opencode stream to parse at %s: %s", stdout_log, e)
        return parsed
    has_text = False
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as e:
            logger.info("[monitor] opencode stream line is not JSON, skipped: %s", e)
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        part = _as_dict(event.get("part"))
        if parsed["session_id"] is None and event.get("sessionID"):
            parsed["session_id"] = event.get("sessionID")
        if kind == "text":
            has_text = True
            parsed["result"] = str(part.get("text", ""))
        elif kind == "step_finish":
            parsed["num_turns"] += 1
            _add_opencode_usage(parsed, part)
        elif kind == "error" and not parsed["error"]:
            parsed["error"] = line.strip()
            err = _as_dict(event.get("error"))
            parsed["rate_limited"] = err.get("status") == 429 or err.get("type") == "provider.free-limit"
            retry_ms = err.get("retryAfterMs")
            if isinstance(retry_ms, (int, float)):
                parsed["retry_after_s"] = int(retry_ms // 1000)
    parsed["succeeded"] = has_text and not parsed["error"]
    return parsed


def _as_dict(value: object) -> dict:
    """`value` when it is an object, else an empty one: a stream field may be absent or malformed."""
    return value if isinstance(value, dict) else {}


def _add_opencode_usage(parsed: dict, part: dict) -> None:
    """Fold one step_finish's tokens and cost into the running totals, in the report's usage shape."""
    tokens = _as_dict(part.get("tokens"))
    cache = _as_dict(tokens.get("cache"))
    usage = parsed["usage"] or {}
    for key, value in (
        ("input_tokens", tokens.get("input")),
        ("output_tokens", tokens.get("output")),
        ("reasoning_tokens", tokens.get("reasoning")),
        ("cache_read_input_tokens", cache.get("read")),
        ("cache_creation_input_tokens", cache.get("write")),
    ):
        if isinstance(value, (int, float)):
            usage[key] = usage.get(key, 0) + value
    parsed["usage"] = usage
    cost = part.get("cost")
    if isinstance(cost, (int, float)):
        parsed["total_cost_usd"] = (parsed["total_cost_usd"] or 0) + cost


def reconcile_opencode_pointer(branch_path: Path, stdout_log: str) -> None:
    """Record the session the stream ran in, when it is not already the pointer's."""
    session_id = parse_opencode_stream(stdout_log)["session_id"]
    if not isinstance(session_id, str) or not session_id.strip():
        logger.warning("[monitor] opencode stream for %s carried no sessionID — pointer unchanged", branch_path)
        return
    pointer = session_pointer.read_pointer(branch_path)
    if pointer is not None and pointer.get("session_id") == session_id and pointer.get("provider") == OPENCODE:
        return
    if not session_pointer.write_pointer(branch_path, session_id.strip(), "monitor-opencode", provider=OPENCODE):
        logger.warning("[monitor] Could not record opencode session %s for %s", session_id, branch_path)


# Exit 0 with this marker is incomplete, not success: the ceiling killed the tasks, maybe the reply.
BG_TASKS_MARKER = "Background tasks still running"


def _rotate_attempt_stdout(stdout_log: str, attempt: int) -> None:
    """Preserve a failed attempt's stdout as dispatch_stdout.attempt-N.log.

    The next attempt truncates stdout, and its result JSON is the only record of the cause.
    """
    try:
        src = Path(stdout_log)
        if src.exists() and src.stat().st_size > 0:
            src.replace(src.parent / f"dispatch_stdout.attempt-{attempt}.log")
    except OSError as e:
        logger.warning("[monitor] Failed to preserve attempt %d stdout: %s", attempt, e)


def _parse_result_json(stdout_log: str) -> dict:
    """Parse the print-mode result JSON from an attempt's stdout log."""
    try:
        content = Path(stdout_log).read_text(encoding="utf-8").strip()
    except OSError as e:
        logger.info("[monitor] No stdout log to parse at %s: %s", stdout_log, e)
        return {}
    if not content:
        return {}
    lines = [ln for ln in content.splitlines() if ln.strip()]
    for candidate in (content, lines[-1] if lines else ""):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            logger.info("[monitor] Result JSON candidate parse failed — trying next form")
            continue
    return {}


def _summarize_result_json(stdout_log: str, provider: str = "claude") -> str:
    """One-line diagnostic summary of the result JSON for bounce emails."""
    if provider == CODEX:
        stream = parse_codex_stream(stdout_log)
        if stream["error"]:
            return f"codex error event: {stream['error'][:400]}"
        if not stream["succeeded"]:
            return f"codex turn never completed, last agent_message: {stream['result'][:400] or '(none)'}"
        return f"codex turn completed, last agent_message: {stream['result'][:400]}"
    if provider == OPENCODE:
        stream = parse_opencode_stream(stdout_log)
        if stream["error"]:
            retry = f" (retryAfter {stream['retry_after_s']}s)" if stream["retry_after_s"] is not None else ""
            return f"opencode error event{retry}: {stream['error'][:400]}"
        if not stream["succeeded"]:
            return "opencode run ended without a text part"
        return f"opencode run answered, last text: {stream['result'][:400]}"
    data = _parse_result_json(stdout_log)
    if not data:
        return "(no result JSON captured)"
    snippet = str(data.get("result", ""))[:400]
    return (
        f"is_error={data.get('is_error')}, subtype={data.get('subtype')}, "
        f"api_error_status={data.get('api_error_status')}, result: {snippet}"
    )


def _read_stderr_segment(stderr_log: str, offset: int) -> str:
    """Read stderr content written after byte offset (one attempt's slice).

    The log is append-mode across runs; the whole file would match earlier attempts' markers.
    """
    try:
        with open(stderr_log, "r", encoding="utf-8") as f:
            f.seek(offset)
            return f.read()
    except OSError as e:
        logger.warning("[monitor] Failed reading stderr segment of %s: %s", stderr_log, e)
        return ""


def _cleanup_own_lock(lock_file: str) -> None:
    """Delete the dispatch lock only if this monitor still owns it.

    A successor monitor may have re-created it while our agent drained; unreadable locks are left.
    """
    lock_path = Path(lock_file)
    if not lock_path.exists():
        return
    try:
        lock_pid = json.loads(lock_path.read_text(encoding="utf-8")).get("pid")
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[monitor] Lock %s unreadable (%s) — leaving it in place", lock_file, e)
        return
    if lock_pid != os.getpid():
        logger.warning(
            "[monitor] Lock %s owned by PID %s, not us (%d) — leaving it in place",
            lock_file,
            lock_pid,
            os.getpid(),
        )
        return
    try:
        lock_path.unlink()
    except OSError:
        logger.info("[monitor] Failed to clean up lock file %s", lock_file)


def _snapshot_jsonl_sizes(projects_dir: Path) -> dict:
    """Snapshot current sizes of all JSONL files in the projects directory."""
    sizes = {}
    if not projects_dir.exists():
        return sizes
    try:
        for f in projects_dir.glob("*.jsonl"):
            try:
                sizes[f.name] = f.stat().st_size
            except OSError as e:
                logger.warning("[monitor] _snapshot_jsonl_sizes stat failed for %s: %s", f.name, e)
    except OSError as e:
        logger.warning("[monitor] _snapshot_jsonl_sizes glob failed for %s: %s", projects_dir, e)
    return sizes


def _check_jsonl_activity(projects_dir: Path, initial_sizes: dict) -> bool:
    """Check if any JSONL file has grown or a new file appeared since snapshot."""
    if not projects_dir.exists():
        return False
    try:
        for f in projects_dir.glob("*.jsonl"):
            try:
                name = f.name
                current_size = f.stat().st_size
                if name not in initial_sizes:
                    if current_size > 0:
                        return True
                elif current_size > initial_sizes[name]:
                    return True
            except OSError as e:
                logger.warning("[monitor] _check_jsonl_activity stat failed for %s: %s", f.name, e)
    except OSError as e:
        logger.warning("[monitor] _check_jsonl_activity glob failed for %s: %s", projects_dir, e)
    return False


def _kill_process(process: subprocess.Popen, branch_email: str):
    """Kill a subprocess gracefully, then forcefully."""
    try:
        process.terminate()
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        logger.warning("[monitor] %s didn't terminate — sending SIGKILL", branch_email)
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("[monitor] %s SIGKILL didn't work", branch_email)


def _stdout_written(stdout_log: str) -> bool:
    """True once the attempt's stdout holds a byte: Codex and OpenCode stream JSON live."""
    try:
        return Path(stdout_log).stat().st_size > 0
    except OSError as e:
        logger.info("[monitor] stdout %s not stattable yet: %s", stdout_log, e)
        return False


def run_with_startup_check(
    claude_cmd: list,
    stdout_log: str,
    stderr_fh,
    cwd: str,
    spawn_env: dict,
    branch_email: str,
    pass_fds: tuple = (),
    provider: str = "claude",
) -> tuple:
    """
    Run claude with startup timeout check.

    A door: main() runs every attempt through it, and the tests drive main() with it as the seam.
    Returns (exit_code, startup_failed); exit_code -1 is the hard timeout, -3 the startup timeout.
    """
    # Truncate: max_turns detection reads the whole file.
    stdout_fh = None
    try:
        stdout_fh = open(stdout_log, "w", encoding="utf-8")
    except OSError as e:
        logger.warning("[monitor] Failed to open stdout log %s: %s", stdout_log, e)

    try:
        popen_kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": stdout_fh if stdout_fh is not None else subprocess.DEVNULL,
            "stderr": stderr_fh,
            "cwd": cwd,
            "env": spawn_env,
        }
        if pass_fds:
            popen_kwargs["close_fds"] = True
            popen_kwargs["pass_fds"] = pass_fds
        process = subprocess.Popen(claude_cmd, **popen_kwargs)
    except Exception as e:
        logger.warning("[monitor] Failed to spawn %s: %s", branch_email, e)
        if stdout_fh is not None:
            stdout_fh.close()
        return -2, False

    # Claude's startup is read from the JSONL transcripts: --output-format json buffers stdout.
    projects_dir = None if provider in STREAMING_PROVIDERS else session_pointer.transcript_dir(cwd)
    if projects_dir is None and provider not in STREAMING_PROVIDERS:
        # After the spawn: raising would orphan a live agent with the lock held. The probe is optional.
        logger.warning("[monitor] no home directory — skipping the JSONL startup probe for %s", cwd)
    initial_sizes = _snapshot_jsonl_sizes(projects_dir) if projects_dir else {}
    deadline = time.time() + STARTUP_TIMEOUT
    started = False

    try:
        while time.time() < deadline:
            if provider in STREAMING_PROVIDERS and _stdout_written(stdout_log):
                started = True
                break
            if projects_dir is not None and _check_jsonl_activity(projects_dir, initial_sizes):
                started = True
                break

            if process.poll() is not None:
                return process.returncode, not started

            time.sleep(POLL_INTERVAL)

        if not started and process.poll() is None:
            logger.warning(
                "[monitor] %s no startup activity after %ds — startup timeout (killing)", branch_email, STARTUP_TIMEOUT
            )
            _kill_process(process, branch_email)
            return -3, True

        try:
            process.wait(timeout=HARD_TIMEOUT)
        except subprocess.TimeoutExpired:
            logger.warning("[monitor] %s timed out after %ds hard limit", branch_email, HARD_TIMEOUT)
            _kill_process(process, branch_email)
            return -1, False

        return process.returncode, False
    finally:
        if stdout_fh is not None:
            stdout_fh.close()


def _final_result_json(stdout_log: str, provider: str) -> dict:
    """The run's result in the report's shape, from the provider's own stdout form."""
    if provider == CODEX:
        return parse_codex_stream(stdout_log)
    if provider == OPENCODE:
        return parse_opencode_stream(stdout_log)
    return _parse_result_json(stdout_log)


def prepend_to_path(path_value: str, entry: str, sep: str = os.pathsep) -> str:
    """Return PATH with entry first, joined by the host's separator.

    Never a literal ":": it follows every Windows drive letter. sep is a parameter for tests.
    """
    return sep.join([entry, path_value]) if path_value else entry


def main():
    """
    Usage: dispatch_monitor.py <branch_email> <lock_file> <sender> <stderr_log> [--no-wake-back]
           [--provider=codex|opencode] [--opencode-config=<json>] -- <agent_argv...>

    --no-wake-back declines the completion wake-back; sender is still used for bounce mail.
    """
    if len(sys.argv) < 6 or "--" not in sys.argv:
        logger.warning("[monitor] Invalid arguments: %s", sys.argv)
        sys.exit(1)

    sep_idx = sys.argv.index("--")
    branch_email = sys.argv[1]
    lock_file = sys.argv[2]
    sender = sys.argv[3]
    stderr_log = sys.argv[4]
    # Only the window before "--": everything after it is claude's argv.
    monitor_flags = sys.argv[5:sep_idx]
    wake_back = NO_WAKE_BACK_FLAG not in monitor_flags
    provider = next(
        (flag[len(PROVIDER_FLAG_PREFIX) :] for flag in monitor_flags if flag.startswith(PROVIDER_FLAG_PREFIX)),
        "claude",
    )
    opencode_config = next(
        (
            flag[len(OPENCODE_CONFIG_FLAG_PREFIX) :]
            for flag in monitor_flags
            if flag.startswith(OPENCODE_CONFIG_FLAG_PREFIX)
        ),
        "",
    )
    claude_cmd = sys.argv[sep_idx + 1 :]

    if not claude_cmd:
        logger.warning("[monitor] No claude command after --")
        sys.exit(1)

    json_handler.log_operation("dispatch_monitor_start", {"branch": branch_email, "sender": sender})

    # The lock may hold the parent's pre-spawn PID, or the caller's under systemd-run.
    try:
        lock_path_obj = Path(lock_file)
        if lock_path_obj.exists():
            ld = json.loads(lock_path_obj.read_text(encoding="utf-8"))
            ld["pid"] = os.getpid()
            lock_path_obj.write_text(json.dumps(ld, indent=2), encoding="utf-8")
    except (json.JSONDecodeError, OSError):
        logger.info("[monitor] Could not self-register PID in lock file %s", lock_file)

    stderr_fh = None
    try:
        stderr_path = Path(stderr_log)
        if stderr_path.exists() and stderr_path.stat().st_size > 512_000:
            rotated = stderr_path.with_suffix(".log.1")
            stderr_path.replace(rotated)
        stderr_fh = open(stderr_log, "a", encoding="utf-8")
        stderr_fh.write(
            f"\n--- Monitor for {branch_email} started at "
            f"{time.strftime('%Y-%m-%dT%H:%M:%S')} (PID {os.getpid()}) ---\n"
        )
        stderr_fh.flush()
    except OSError as e:
        logger.warning("[monitor] Failed to open stderr log %s: %s", stderr_log, e)

    spawn_env = os.environ.copy()
    spawn_env["AIPASS_SPAWNED"] = "1"
    spawn_env["AIPASS_SESSION_TYPE"] = "dispatched"
    from aipass.ai_mail.apps.handlers.paths import find_repo_root

    _repo_root = find_repo_root()
    venv_bin = str(_repo_root / ".venv" / "bin")
    if venv_bin not in spawn_env.get("PATH", ""):
        spawn_env["PATH"] = prepend_to_path(spawn_env.get("PATH", ""), venv_bin)
    # Background launchers (trigger, prax watchdog) may run with a restricted PATH.
    local_bin = str(Path.home() / ".local" / "bin")
    if local_bin not in spawn_env.get("PATH", ""):
        spawn_env["PATH"] = prepend_to_path(spawn_env.get("PATH", ""), local_bin)
    for key in list(spawn_env.keys()):
        if key.startswith("CLAUDE") or key == "AIPASS_BOT_ID":
            spawn_env.pop(key)
        # A parent OpenCode's session markers must not reach the child; the store both ends read stays.
        elif key.startswith("OPENCODE") and key != session_pointer.OPENCODE_DB_ENV:
            spawn_env.pop(key)
    # After the strip, from argv only: a parent seat's own OPENCODE_CONFIG_CONTENT never reaches the child.
    if opencode_config:
        spawn_env[OPENCODE_CONFIG_ENV] = opencode_config
    # 350k for every model, else an agent inherits its native window (1M). After the CLAUDE* strip.
    spawn_env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "350000"
    spawn_env.pop("AIPASS_CALLER_BRANCH", None)
    spawn_env.pop("AIPASS_CALLER_CWD", None)
    # Drone's fallback for caller detection once the agent cd's away.
    spawn_env["AIPASS_BRANCH_NAME"] = branch_email.lstrip("@")

    # Resolved: a relative registry path would be read against the monitor's own cwd.
    lock_path = Path(lock_file).resolve()
    branch_path = lock_path.parent.parent
    cwd = str(branch_path)
    # Popen's cwd leaves an inherited PWD naming the caller's directory; OpenCode files its session there.
    spawn_env["PWD"] = cwd

    logs_dir = branch_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = str(logs_dir / "dispatch_stdout.log")
    try:
        stdout_path = Path(stdout_log)
        if stdout_path.exists() and stdout_path.stat().st_size > 512_000:
            rotated = stdout_path.with_suffix(".log.1")
            stdout_path.replace(rotated)
        for stale in logs_dir.glob("dispatch_stdout.attempt-*.log"):
            stale.replace(stale.with_suffix(".log.1"))
    except OSError as e:
        logger.warning("[monitor] Failed to rotate stdout log: %s", e)

    start_time = time.time()

    sandbox_enabled = is_sandbox_enabled()
    if sandbox_enabled:
        logger.info("[monitor] Sandbox ENABLED for %s", branch_email)

    attempts = []
    exit_code = -1
    bg_orphaned = False
    cmd = list(claude_cmd)

    for attempt in range(1, 4):
        cmd, mode = cmd_for_attempt(claude_cmd, attempt, branch_path, provider)
        if attempt == 3 and mode == "fresh" and cmd != claude_cmd:
            logger.info("[monitor] %s attempt %d/3: switching to --fresh", branch_email, attempt)

        # On failure: abort, NEVER silently launch unsandboxed.
        run_cmd = cmd
        broker_sock = None
        attempt_pass_fds: tuple = ()
        if sandbox_enabled:
            try:
                run_cmd = wrap_for_sandbox(cmd, branch_path)
            except Exception as e:
                logger.error(
                    "[monitor] Sandbox init FAILED for %s: %s — ABORTING (will NOT launch unsandboxed)",
                    branch_email,
                    e,
                )
                exit_code = -4
                attempts.append({"attempt": attempt, "exit_code": exit_code, "startup_failed": False, "mode": mode})
                break

            try:
                broker_sock = _connect_broker(_repo_root, branch_email.lstrip("@"))
                broker_fd = broker_sock.fileno()
                spawn_env["AIPASS_BROKER_FD"] = str(broker_fd)
                attempt_pass_fds = (broker_fd,)
                logger.info("[monitor] Broker fd %d connected for %s", broker_fd, branch_email)
            except Exception as e:
                logger.error(
                    "[monitor] Broker connect FAILED for %s: %s — ABORTING",
                    branch_email,
                    e,
                )
                exit_code = -4
                attempts.append({"attempt": attempt, "exit_code": exit_code, "startup_failed": False, "mode": mode})
                break

        attempt_stderr_offset = None
        if stderr_fh is not None:
            stderr_fh.write(f"\n--- Attempt {attempt}/3 ({mode}) at {time.strftime('%H:%M:%S')} ---\n")
            stderr_fh.flush()
            attempt_stderr_offset = stderr_fh.tell()

        exit_code, startup_failed = run_with_startup_check(
            run_cmd,
            stdout_log,
            stderr_fh if stderr_fh is not None else subprocess.DEVNULL,
            cwd,
            spawn_env,
            branch_email,
            pass_fds=attempt_pass_fds,
            provider=provider,
        )
        if provider == CODEX and exit_code == 0 and not parse_codex_stream(stdout_log)["succeeded"]:
            logger.warning("[monitor] %s codex exited 0 without a clean turn.completed — failed", branch_email)
            exit_code = CODEX_STREAM_FAILED
        opencode_stream = parse_opencode_stream(stdout_log) if provider == OPENCODE else None
        if opencode_stream is not None:
            # Every attempt, failed ones too: OpenCode minted the session, so a resume needs its id.
            reconcile_opencode_pointer(branch_path, stdout_log)
        if opencode_stream is not None and exit_code == 0 and not opencode_stream["succeeded"]:
            logger.warning("[monitor] %s opencode exited 0 without a text part — failed", branch_email)
            exit_code = OPENCODE_STREAM_FAILED

        if broker_sock is not None:
            broker_sock.close()
            broker_sock = None
            spawn_env.pop("AIPASS_BROKER_FD", None)

        attempts.append({"attempt": attempt, "exit_code": exit_code, "startup_failed": startup_failed, "mode": mode})

        if stderr_fh is not None:
            try:
                note = " (startup timeout)" if startup_failed else ""
                stderr_fh.write(f"--- Attempt {attempt}/3 exited: code={exit_code}{note} ---\n")
                stderr_fh.flush()
            except OSError:
                logger.info("[monitor] Failed to write attempt exit line")

        if exit_code == 0:
            if attempt_stderr_offset is not None and BG_TASKS_MARKER in _read_stderr_segment(
                stderr_log, attempt_stderr_offset
            ):
                bg_orphaned = True
            if attempt > 1:
                logger.info("[monitor] %s succeeded on attempt %d/3", branch_email, attempt)
            break

        if exit_code in (CODEX_STREAM_FAILED, OPENCODE_STREAM_FAILED):
            # The turn ran and may have acted (mail, memories); a re-run would repeat that work.
            break
        if opencode_stream is not None and opencode_stream["error"]:
            # The stream named its failure (no route, free limit): a re-run meets the same answer.
            logger.warning("[monitor] %s opencode error event: %s", branch_email, opencode_stream["error"][:400])
            break

        if startup_failed:
            logger.warning(
                "[monitor] %s attempt %d/3: startup timeout (zero output after %ds)",
                branch_email,
                attempt,
                STARTUP_TIMEOUT,
            )
        else:
            logger.warning("[monitor] %s attempt %d/3: exit code %d", branch_email, attempt, exit_code)

        if attempt >= 3:
            break

        _rotate_attempt_stdout(stdout_log, attempt)

        if _check_rate_limited(stderr_log):
            logger.info("[monitor] %s rate limited — waiting %ds before retry", branch_email, RATE_LIMIT_DELAY)
            time.sleep(RATE_LIMIT_DELAY)
        else:
            time.sleep(5)  # Brief pause between retries

    duration = int(time.time() - start_time)

    # Success only. `cmd` is the LAST attempt's: strike 3 remints, so the original would misreport.
    if exit_code == 0 and provider == CODEX:
        reconcile_codex_pointer(branch_path, stdout_log)
    elif exit_code == 0 and provider != OPENCODE:
        reconcile_pointer(branch_path, stdout_log, cmd)

    max_turns_hit = False
    try:
        with open(stdout_log, "r", encoding="utf-8") as f:
            stdout_content = f.read()
        if '"stop_reason":"max_turns"' in stdout_content or '"stop_reason": "max_turns"' in stdout_content:
            max_turns_hit = True
            logger.warning("[monitor] %s HIT MAX TURNS after %ds — work may be incomplete", branch_email, duration)
    except OSError as e:
        logger.warning("[monitor] Failed to read stdout log for max-turns check: %s", e)

    if stderr_fh is not None:
        try:
            suffix = " [MAX TURNS HIT]" if max_turns_hit else ""
            if bg_orphaned:
                suffix += " [BG TASKS TERMINATED — INCOMPLETE]"
            retry_note = f" (took {len(attempts)} attempts)" if len(attempts) > 1 else ""
            stderr_fh.write(f"\n--- Agent exited: code={exit_code}, duration={duration}s{suffix}{retry_note} ---\n")
            stderr_fh.flush()
        except OSError:
            logger.info("[monitor] Failed to write agent exit log")
        finally:
            stderr_fh.close()

    bounce_delivered = True
    if exit_code != 0:
        attempt_details = []
        for a in attempts:
            if a["startup_failed"]:
                detail = f"Attempt {a['attempt']} ({a['mode']}): startup timeout"
            else:
                detail = f"Attempt {a['attempt']} ({a['mode']}): exit code {a['exit_code']}"
            attempt_details.append(detail)

        reason = f"All {len(attempts)} attempts failed after {duration}s.\n" + "\n".join(attempt_details)

        content = _read_agent_stderr(stderr_log)
        final_stream = parse_opencode_stream(stdout_log) if provider == OPENCODE else {}
        if final_stream.get("rate_limited"):
            retry = final_stream["retry_after_s"]
            reason = (
                f"API rate limit (opencode 429, retryAfter {retry if retry is not None else 'unknown'}s, {duration}s)"
            )
        elif "rate_limit" in content.lower() or "429" in content:
            reason = f"API rate limit (all {len(attempts)} attempts failed, {duration}s)"
        elif "overloaded" in content.lower() or "529" in content:
            reason = f"API overloaded (all {len(attempts)} attempts failed, {duration}s)"

        reason += f"\n\nLast attempt result JSON: {_summarize_result_json(stdout_log, provider)}"

        bounce_delivered = _note_undelivered_bounce(
            _send_bounce(branch_email, reason, sender, lock_file, stderr_log), branch_email, reason, sender
        )
    elif bg_orphaned:
        logger.warning(
            "[monitor] %s exited 0 but background tasks were still running — treating as INCOMPLETE", branch_email
        )
        reason = (
            f"Agent exited 0 after {duration}s but background tasks were still running and were "
            f"terminated at the headless print-mode ceiling. Work handed to those tasks is gone "
            f"and no reply may have been sent — re-dispatch if the task is not complete.\n\n"
            f"Result JSON: {_summarize_result_json(stdout_log, provider)}"
        )
        bounce_delivered = _note_undelivered_bounce(
            _send_bounce(branch_email, reason, sender, lock_file, stderr_log), branch_email, reason, sender
        )

    # Log completion to Prax (tests/test_dispatch_completion_ordering.py anchors on this line)
    branch_name = branch_email.lstrip("@")
    status = "completed" if exit_code == 0 else f"FAILED (code {exit_code})"
    if bg_orphaned:
        status = f"INCOMPLETE (bg tasks terminated, {duration}s)"
    if max_turns_hit:
        status = f"MAX TURNS HIT ({duration}s)"
    # The outcome field the report, the register's close and the feed title share.
    if not bounce_delivered:
        status = f"{status}, bounce NOT delivered to {sender}"
    logger.info("[monitor] @%s %s — %ds", branch_name, status, duration)

    # Before the report, so wake_result is known when it is assembled.
    if wake_back:
        wake_result = wake_sender(sender, branch_email, exit_code, target_home=branch_path)
    else:
        logger.info(
            "[monitor] Wake-back declined by caller: %s finished, sender %s not woken or mailed",
            branch_email,
            sender,
        )
        wake_result = WAKE_RESULT_DECLINED
    log_wake_result(branch_email, sender, exit_code, wake_result, lock_file)

    # The report is written BEFORE the lock is released: a death in between then leaves a
    # visible, recoverable HELD LOCK instead of a released lock and no report.
    report_path = None
    dispatch_id = report_mod.current_dispatch_id()
    try:
        report = report_mod.build_report(
            dispatch_id=dispatch_id,
            sender=sender,
            target=branch_email,
            branch_path=branch_path,
            start_time=start_time,
            duration=duration,
            exit_code=exit_code,
            status=status,
            attempts=attempts,
            bg_orphaned=bg_orphaned,
            max_turns_hit=max_turns_hit,
            wake_result=wake_result,
            result_json=_final_result_json(stdout_log, provider),
        )
        report_path = report_mod.write_report(report)
        if report_path is None:
            logger.warning(
                "[monitor] REPORT LOST for %s (%s) — no durable record of this dispatch: %s",
                branch_email,
                dispatch_id,
                report,
            )
    except Exception as e:
        logger.warning("[monitor] report assembly failed for %s: %s", branch_email, e)

    if dispatch_id:
        register.close_dispatch(dispatch_id, status, report_path)

    # The feed carries the event across processes (trigger cannot). Additive fields only:
    # @api serves this feed to BAUD, so the line stays a one-line summary.
    try:
        from aipass.ai_mail.apps.handlers.notify import send_notification

        feed_extra = {"dispatch_id": dispatch_id, "sender": sender, "report_path": report_path}
        if not send_notification(
            f"@{branch_name} {status}",
            f"Duration: {duration}s",
            source=branch_name,
            kind="dispatch",
            extra=feed_extra,
        ):
            logger.warning(
                "[monitor] FEED WRITE FAILED for %s — this dispatch will not reach the wire: %s",
                branch_email,
                feed_extra,
            )
    except Exception as e:
        # A failed report write is a LOST DISPATCH RECORD: warn, never info.
        logger.warning(
            "[monitor] Notification feed unavailable for %s (%s, report=%s): %s",
            branch_email,
            status,
            report_path,
            e,
        )

    report_mod.fire_completed(dispatch_id, sender, branch_email, report_path)

    # LAST, and PID-verified.
    _cleanup_own_lock(lock_file)

    sys.exit(0 if exit_code == 0 and not bg_orphaned else 1)


if __name__ == "__main__":
    main()
