# =================== AIPass ====================
# Name: dispatch_monitor.py
# Description: Agent Lifecycle Monitor
# Version: 2.1.0
# Created: 2026-03-02
# Modified: 2026-07-31
# =============================================

"""
Agent Lifecycle Monitor

Wraps a Claude agent spawn. Instead of fire-and-forget Popen, this process:
1. Runs claude with startup health check (90s timeout)
2. Auto-retries on failure (3 strikes: resume, resume, fresh) — each
   attempt's stdout is preserved to dispatch_stdout.attempt-N.log before
   the next attempt truncates it, and each attempt's exit code is logged
   to the branch-local dispatch_stderr.log, not just prax
3. Checks exit code AND whether background tasks were still running at
   the headless print-mode's 600s wait ceiling (exit 0 there is not a
   real success — the CLI gave up waiting, work may be incomplete)
4. On failure: sends return-to-sender bounce email (with the attempt's
   result JSON parsed from stdout for diagnostics)
5. Cleans up the dispatch lock it owns (PID-verified — a successor
   monitor's lock is never deleted)

Spawned by wake.py in place of claude directly. The lock PID points to
the monitor (which stays alive as long as claude does), so lock validity
is guaranteed.
"""

import json
import os
import shlex
import socket
import sys
import subprocess
import time
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

# Startup timeout: if zero stdout after this many seconds, kill and retry
STARTUP_TIMEOUT = 90
# Delay between retries when rate-limited
RATE_LIMIT_DELAY = 30
# Hard timeout for the full agent run
HARD_TIMEOUT = 7200  # 2 hours
# How often to poll stdout during startup check
POLL_INTERVAL = 5


def _is_sandbox_enabled() -> bool:
    """Check if dispatch sandbox is enabled via AIPASS_SANDBOX_ENABLED env var."""
    return os.environ.get("AIPASS_SANDBOX_ENABLED", "").lower() in ("1", "true", "yes")


def _wrap_for_sandbox(cmd: list, branch_path: Path) -> list:
    """Wrap a claude command in the srt kernel sandbox.

    Uses @hooks sandbox building blocks to resolve the bwrap command,
    then returns a shell invocation list compatible with Popen.

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

    Returns a connected, HMAC-authenticated socket ready to be inherited
    by the sandboxed child via pass_fds + AIPASS_BROKER_FD.

    Raises on ANY failure — caller must not silently skip the broker.
    """
    from aipass.drone.apps.handlers.broker.client import create_identified_connection

    socket_path = repo_root / ".ai_central" / "drone_broker.sock"
    secret_path = repo_root / ".ai_central" / "broker_secret"
    return create_identified_connection(socket_path, secret_path, branch_name)


MAX_WAKE_DEPTH = 3


def _wake_sender(sender: str, branch_email: str, exit_code: int, lock_file: str) -> str:
    """Wake the dispatcher back after target completion.

    Any citizen sender gets woken back (same availability checks as
    normal wake — interactive session, active lock, depth cap).

    Returns a result tag for the dispatch_wake.log:
      success, blocked_occupied, blocked_locked, blocked_depth,
      skipped_sender, skipped_self, failed
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
        wake_status, success = wake_branch(sender, auto=True, sender="")

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


def _log_wake_result(branch_email: str, sender: str, exit_code: int, result: str, lock_file: str):
    """Append a wake-back result line to dispatch_wake.log under target's logs/."""
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
    """Send return-to-sender bounce email via drone."""
    subject = f"BOUNCE: Dispatch to {branch_email} failed"

    # Read last few lines of stderr log for diagnostics
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

    # Send via drone (resolves paths, handles routing)
    try:
        result = subprocess.run(
            ["drone", "@ai_mail", "send", sender, subject, body],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(Path(lock_file).parent.parent),
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("[monitor] Bounce email send failed for %s: %s", branch_email, e)
        # Fallback: write bounce to a file if email fails
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
                    },
                    f,
                    indent=2,
                )
        except OSError:
            logger.info("[monitor] Failed to write bounce file fallback")
        return False


def _read_agent_stderr(stderr_log: str) -> str:
    """Read the dispatch stderr log, excluding the monitor's own framing lines.

    The monitor writes header/footer/attempt markers (all prefixed with "--- ")
    that embed the PID and timestamps. Those numbers must NOT be scanned for API
    error markers -- e.g. a PID like 14290 contains "429" and would otherwise be
    misread as an HTTP 429 rate-limit. Returns "" if the log can't be read.
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


def _make_fresh_cmd(claude_cmd: list) -> list:
    """Remove -c flag from claude command to force fresh start."""
    return [arg for arg in claude_cmd if arg != "-c"]


# CLI stderr marker: agent ended its turn with background tasks still alive,
# and the print-mode ceiling terminated them. Exit code is 0 but any work
# those tasks carried (including the reply) is gone — incomplete, not success.
BG_TASKS_MARKER = "Background tasks still running"


def _rotate_attempt_stdout(stdout_log: str, attempt: int) -> None:
    """Preserve a failed attempt's stdout as dispatch_stdout.attempt-N.log.

    The result JSON in stdout is the only artifact naming the failure cause —
    the next attempt truncates the file, destroying that evidence.
    """
    try:
        src = Path(stdout_log)
        if src.exists() and src.stat().st_size > 0:
            src.replace(src.parent / f"dispatch_stdout.attempt-{attempt}.log")
    except OSError as e:
        logger.warning("[monitor] Failed to preserve attempt %d stdout: %s", attempt, e)


def _parse_result_json(stdout_log: str) -> dict:
    """Parse the print-mode result JSON from an attempt's stdout log.

    Tries the whole file first, then the last non-empty line (the result
    object is the final line when earlier output precedes it). Returns {}
    when the file is missing, empty, or holds no JSON object.
    """
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


def _summarize_result_json(stdout_log: str) -> str:
    """One-line diagnostic summary of the result JSON for bounce emails."""
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

    The stderr log is shared append-mode across runs — scanning the whole
    file would match markers from previous attempts or previous runs.
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

    A successor monitor may have re-created the lock while our agent was
    draining background tasks past its reply — unconditional unlink would
    strip the successor's occupancy protection (seen live 2026-07-31,
    seedgo double-spawn). Unreadable locks are left for stale-lock cleanup.
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


def _get_jsonl_projects_dir(cwd: str) -> Path:
    """Get Claude's JSONL projects directory for a branch CWD.

    Claude encodes the cwd by replacing path separators and ':' with '-'.
    Windows path ``C:\\repo\\AIPass`` becomes ``C--repo-AIPass``.
    """
    encoded = cwd.replace("\\", "-").replace("/", "-").replace(":", "-").replace("_", "-").replace(".", "-")
    return Path.home() / ".claude" / "projects" / encoded


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
                    # New file appeared
                    if current_size > 0:
                        return True
                elif current_size > initial_sizes[name]:
                    # Existing file grew
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


def _run_with_startup_check(
    claude_cmd: list, stdout_log: str, stderr_fh, cwd: str, spawn_env: dict, branch_email: str, pass_fds: tuple = ()
) -> tuple:
    """
    Run claude with startup timeout check.

    Returns:
        (exit_code, startup_failed: bool)
        exit_code: process return code (-1 = hard timeout, -3 = startup timeout)
        startup_failed: True if killed due to no output within STARTUP_TIMEOUT
    """
    # Open stdout fresh for this attempt (truncate — max_turns detection reads whole file)
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

    # Phase 1: Startup check — poll JSONL session files for activity.
    # stdout is buffered by --output-format json, so we can't use it.
    # Claude writes to ~/.claude/projects/{encoded-cwd}/*.jsonl continuously.
    projects_dir = _get_jsonl_projects_dir(cwd)
    initial_sizes = _snapshot_jsonl_sizes(projects_dir)
    deadline = time.time() + STARTUP_TIMEOUT
    started = False

    try:
        while time.time() < deadline:
            # Check if JSONL files show activity (new file or growth)
            if _check_jsonl_activity(projects_dir, initial_sizes):
                started = True
                break

            # Check if process already exited
            if process.poll() is not None:
                # If no JSONL activity was detected, this is a startup failure
                return process.returncode, not started

            time.sleep(POLL_INTERVAL)

        if not started and process.poll() is None:
            # Startup timeout — no JSONL activity after STARTUP_TIMEOUT seconds
            logger.warning(
                "[monitor] %s no JSONL activity after %ds — startup timeout (killing)", branch_email, STARTUP_TIMEOUT
            )
            _kill_process(process, branch_email)
            return -3, True

        # Phase 2: Agent started — wait for full completion with hard timeout
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


def main():
    """
    Usage: dispatch_monitor.py <branch_email> <lock_file> <sender> <stderr_log> -- <claude_args...>

    Runs claude with startup health check and auto-retry, handles cleanup.
    """
    if len(sys.argv) < 6 or "--" not in sys.argv:
        logger.warning("[monitor] Invalid arguments: %s", sys.argv)
        sys.exit(1)

    sep_idx = sys.argv.index("--")
    branch_email = sys.argv[1]
    lock_file = sys.argv[2]
    sender = sys.argv[3]
    stderr_log = sys.argv[4]
    claude_cmd = sys.argv[sep_idx + 1 :]

    if not claude_cmd:
        logger.warning("[monitor] No claude command after --")
        sys.exit(1)

    json_handler.log_operation("dispatch_monitor_start", {"branch": branch_email, "sender": sender})

    # Self-register PID in lock file — the parent may have written its own
    # PID during pre-spawn lock acquisition (DPLAN-0155), and under
    # systemd-run the parent PID belongs to the caller, not the monitor.
    try:
        lock_path_obj = Path(lock_file)
        if lock_path_obj.exists():
            ld = json.loads(lock_path_obj.read_text(encoding="utf-8"))
            ld["pid"] = os.getpid()
            lock_path_obj.write_text(json.dumps(ld, indent=2), encoding="utf-8")
    except (json.JSONDecodeError, OSError):
        logger.info("[monitor] Could not self-register PID in lock file %s", lock_file)

    # Open stderr log for claude output (rotate if > 500KB)
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

    # Prepare env — strip CLAUDE* vars and AIPASS_BOT_ID
    spawn_env = os.environ.copy()
    spawn_env["AIPASS_SPAWNED"] = "1"
    spawn_env["AIPASS_SESSION_TYPE"] = "dispatched"
    # Guarantee venv bin is on PATH so agents can find drone/claude
    from aipass.ai_mail.apps.handlers.paths import find_repo_root

    _repo_root = find_repo_root()
    venv_bin = str(_repo_root / ".venv" / "bin")
    if venv_bin not in spawn_env.get("PATH", ""):
        spawn_env["PATH"] = venv_bin + ":" + spawn_env.get("PATH", "")
    # Guarantee ~/.local/bin is on PATH for pip-installed tools (e.g. claude)
    # Background processes (trigger, prax watchdog) may have restricted PATH.
    local_bin = str(Path.home() / ".local" / "bin")
    if local_bin not in spawn_env.get("PATH", ""):
        spawn_env["PATH"] = local_bin + ":" + spawn_env.get("PATH", "")
    for key in list(spawn_env.keys()):
        if key.startswith("CLAUDE") or key == "AIPASS_BOT_ID":
            spawn_env.pop(key)
    # Pin agent context window to 200k (Sonnet 5 is 1M native; without this,
    # agents inherit 1M which causes cost + runaway risk).
    spawn_env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "200000"
    # Strip caller identity vars to prevent dispatch context leakage.
    spawn_env.pop("AIPASS_CALLER_BRANCH", None)
    spawn_env.pop("AIPASS_CALLER_CWD", None)
    # Set CWD-independent branch identity so agent knows who it is
    # even after cd'ing away. Drone reads this as fallback for caller detection.
    spawn_env["AIPASS_BRANCH_NAME"] = branch_email.lstrip("@")

    # Extract CWD from lock file path (branch_path/.ai_mail.local/.dispatch.lock).
    # Resolve to absolute so the cwd passed to claude is never relative — a relative
    # cwd would be interpreted against dispatch_monitor's own cwd and produce the
    # wrong directory for branches like @ai_mail whose registry path is relative.
    lock_path = Path(lock_file).resolve()
    branch_path = lock_path.parent.parent
    cwd = str(branch_path)

    # Stdout log setup (rotate if > 500KB before first attempt)
    logs_dir = branch_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = str(logs_dir / "dispatch_stdout.log")
    try:
        stdout_path = Path(stdout_log)
        if stdout_path.exists() and stdout_path.stat().st_size > 512_000:
            rotated = stdout_path.with_suffix(".log.1")
            stdout_path.replace(rotated)
        # Shift the previous run's per-attempt stdout logs aside so this
        # run's attempt files can't be confused with stale ones
        for stale in logs_dir.glob("dispatch_stdout.attempt-*.log"):
            stale.replace(stale.with_suffix(".log.1"))
    except OSError as e:
        logger.warning("[monitor] Failed to rotate stdout log: %s", e)

    start_time = time.time()

    # ─── Sandbox Gate ─────────────────────────────────────
    sandbox_enabled = _is_sandbox_enabled()
    if sandbox_enabled:
        logger.info("[monitor] Sandbox ENABLED for %s", branch_email)

    # ─── Retry Loop: 3 Strikes ─────────────────────────────
    # Strike 1: original command (resume if -c was passed)
    # Strike 2: same command again (transient failure)
    # Strike 3: fresh start (remove -c, abandon potentially corrupted session)
    attempts = []
    exit_code = -1
    bg_orphaned = False
    has_resume = "-c" in claude_cmd

    for attempt in range(1, 4):
        # Strike 3: switch to fresh if original was resume
        if attempt == 3 and has_resume:
            cmd = _make_fresh_cmd(claude_cmd)
            mode = "fresh"
            logger.info("[monitor] %s attempt %d/3: switching to --fresh", branch_email, attempt)
        else:
            cmd = claude_cmd
            mode = "resume" if has_resume else "fresh"

        # Sandbox wrap + broker fd: when enabled, wrap cmd and connect broker.
        # On failure: abort — NEVER silently launch unsandboxed.
        run_cmd = cmd
        broker_sock = None
        attempt_pass_fds: tuple = ()
        if sandbox_enabled:
            try:
                run_cmd = _wrap_for_sandbox(cmd, branch_path)
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

        # Track where this attempt's stderr starts — append mode means
        # tell() after flush is the real end-of-file
        attempt_stderr_offset = None
        if stderr_fh is not None:
            stderr_fh.write(f"\n--- Attempt {attempt}/3 ({mode}) at {time.strftime('%H:%M:%S')} ---\n")
            stderr_fh.flush()
            attempt_stderr_offset = stderr_fh.tell()

        exit_code, startup_failed = _run_with_startup_check(
            run_cmd,
            stdout_log,
            stderr_fh if stderr_fh is not None else subprocess.DEVNULL,
            cwd,
            spawn_env,
            branch_email,
            pass_fds=attempt_pass_fds,
        )

        # Close parent's broker socket copy — child owns the fd now.
        if broker_sock is not None:
            broker_sock.close()
            broker_sock = None
            spawn_env.pop("AIPASS_BROKER_FD", None)

        attempts.append({"attempt": attempt, "exit_code": exit_code, "startup_failed": startup_failed, "mode": mode})

        # Record each attempt's outcome in the dispatch stderr log itself —
        # per-attempt exit codes otherwise only reach prax logs
        if stderr_fh is not None:
            try:
                note = " (startup timeout)" if startup_failed else ""
                stderr_fh.write(f"--- Attempt {attempt}/3 exited: code={exit_code}{note} ---\n")
                stderr_fh.flush()
            except OSError:
                logger.info("[monitor] Failed to write attempt exit line")

        # Success — done, unless the CLI terminated still-running background
        # tasks at the print-mode ceiling (exit 0 but work incomplete)
        if exit_code == 0:
            if attempt_stderr_offset is not None and BG_TASKS_MARKER in _read_stderr_segment(
                stderr_log, attempt_stderr_offset
            ):
                bg_orphaned = True
            if attempt > 1:
                logger.info("[monitor] %s succeeded on attempt %d/3", branch_email, attempt)
            break

        # Log failure
        if startup_failed:
            logger.warning(
                "[monitor] %s attempt %d/3: startup timeout (zero output after %ds)",
                branch_email,
                attempt,
                STARTUP_TIMEOUT,
            )
        else:
            logger.warning("[monitor] %s attempt %d/3: exit code %d", branch_email, attempt, exit_code)

        # No more retries
        if attempt >= 3:
            break

        # Preserve this attempt's stdout (its result JSON is the failure
        # evidence) before the next attempt truncates the file
        _rotate_attempt_stdout(stdout_log, attempt)

        # Rate limit — longer delay before retry
        if _check_rate_limited(stderr_log):
            logger.info("[monitor] %s rate limited — waiting %ds before retry", branch_email, RATE_LIMIT_DELAY)
            time.sleep(RATE_LIMIT_DELAY)
        else:
            time.sleep(5)  # Brief pause between retries

    duration = int(time.time() - start_time)

    # ─── Post-Processing ───────────────────────────────────

    # Check for max-turns hit (Claude exits 0 but output contains stop_reason)
    max_turns_hit = False
    try:
        with open(stdout_log, "r", encoding="utf-8") as f:
            stdout_content = f.read()
        if '"stop_reason":"max_turns"' in stdout_content or '"stop_reason": "max_turns"' in stdout_content:
            max_turns_hit = True
            logger.warning("[monitor] %s HIT MAX TURNS after %ds — work may be incomplete", branch_email, duration)
    except OSError as e:
        logger.warning("[monitor] Failed to read stdout log for max-turns check: %s", e)

    # Log completion to stderr and close
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

    # Handle failure — bounce with all attempt details
    if exit_code != 0:
        # Build reason from all attempts
        attempt_details = []
        for a in attempts:
            if a["startup_failed"]:
                detail = f"Attempt {a['attempt']} ({a['mode']}): startup timeout"
            else:
                detail = f"Attempt {a['attempt']} ({a['mode']}): exit code {a['exit_code']}"
            attempt_details.append(detail)

        reason = f"All {len(attempts)} attempts failed after {duration}s.\n" + "\n".join(attempt_details)

        # Check stderr for specific error categories. Exclude the monitor's own
        # framing lines (PID/timestamp headers) so a number like a PID containing
        # "429" is not misread as an HTTP 429 rate-limit response.
        content = _read_agent_stderr(stderr_log)
        if "rate_limit" in content.lower() or "429" in content:
            reason = f"API rate limit (all {len(attempts)} attempts failed, {duration}s)"
        elif "overloaded" in content.lower() or "529" in content:
            reason = f"API overloaded (all {len(attempts)} attempts failed, {duration}s)"

        # Attach the last attempt's parsed result JSON — names the actual
        # failure cause instead of just the exit code
        reason += f"\n\nLast attempt result JSON: {_summarize_result_json(stdout_log)}"

        _send_bounce(branch_email, reason, sender, lock_file, stderr_log)
    elif bg_orphaned:
        # Exit 0 but the CLI killed still-running background tasks — the
        # agent's deferred work (possibly including its reply) never ran
        logger.warning(
            "[monitor] %s exited 0 but background tasks were still running — treating as INCOMPLETE", branch_email
        )
        reason = (
            f"Agent exited 0 after {duration}s but background tasks were still running and were "
            f"terminated at the headless print-mode ceiling. Work handed to those tasks is gone "
            f"and no reply may have been sent — re-dispatch if the task is not complete.\n\n"
            f"Result JSON: {_summarize_result_json(stdout_log)}"
        )
        _send_bounce(branch_email, reason, sender, lock_file, stderr_log)

    # Clean up the lock — PID-verified, never a successor monitor's lock
    _cleanup_own_lock(lock_file)

    # Log completion to Prax
    branch_name = branch_email.lstrip("@")
    status = "completed" if exit_code == 0 else f"FAILED (code {exit_code})"
    if bg_orphaned:
        status = f"INCOMPLETE (bg tasks terminated, {duration}s)"
    if max_turns_hit:
        status = f"MAX TURNS HIT ({duration}s)"
    logger.info("[monitor] @%s %s — %ds", branch_name, status, duration)

    # Desktop notification on completion
    try:
        from aipass.ai_mail.apps.handlers.notify import send_notification

        icon = "dialog-information" if exit_code == 0 and not bg_orphaned else "dialog-warning"
        send_notification(f"@{branch_name} {status}", f"Duration: {duration}s", source=branch_name, icon=icon)
    except Exception:
        logger.info("[monitor] Desktop notification unavailable")

    # ─── Wake-back: wake the dispatcher ────────────────────
    wake_result = _wake_sender(sender, branch_email, exit_code, lock_file)
    _log_wake_result(branch_email, sender, exit_code, wake_result, lock_file)

    sys.exit(0 if exit_code == 0 and not bg_orphaned else 1)


if __name__ == "__main__":
    main()
