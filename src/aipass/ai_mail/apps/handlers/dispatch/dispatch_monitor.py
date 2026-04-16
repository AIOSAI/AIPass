# =================== AIPass ====================
# Name: dispatch_monitor.py
# Description: Agent Lifecycle Monitor
# Version: 2.0.0
# Created: 2026-03-02
# Modified: 2026-04-02
# =============================================

"""
Agent Lifecycle Monitor

Wraps a Claude agent spawn. Instead of fire-and-forget Popen, this process:
1. Runs claude with startup health check (90s timeout)
2. Auto-retries on failure (3 strikes: resume, resume, fresh)
3. Checks exit code
4. On failure: sends return-to-sender bounce email
5. Always cleans up the dispatch lock

Spawned by wake.py in place of claude directly. The lock PID points to
the monitor (which stays alive as long as claude does), so lock validity
is guaranteed.
"""

import json
import os
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


def _check_rate_limited(stderr_log: str) -> bool:
    """Check if stderr indicates API rate limiting or overload."""
    try:
        with open(stderr_log, "r", encoding="utf-8") as f:
            content = f.read()
        lower = content.lower()
        return "rate_limit" in lower or "429" in content or "overloaded" in lower or "529" in content
    except OSError as e:
        logger.warning("[monitor] _check_rate_limited failed reading %s: %s", stderr_log, e)
        return False


def _make_fresh_cmd(claude_cmd: list) -> list:
    """Remove -c flag from claude command to force fresh start."""
    return [arg for arg in claude_cmd if arg != "-c"]


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
    claude_cmd: list, stdout_log: str, stderr_fh, cwd: str, spawn_env: dict, branch_email: str
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
        process = subprocess.Popen(
            claude_cmd,
            stdout=stdout_fh if stdout_fh is not None else subprocess.DEVNULL,
            stderr=stderr_fh,
            cwd=cwd,
            env=spawn_env,
        )
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
    # Strip caller identity vars to prevent dispatch context leakage.
    spawn_env.pop("AIPASS_CALLER_BRANCH", None)
    spawn_env.pop("AIPASS_CALLER_CWD", None)
    # Set CWD-independent branch identity so agent knows who it is
    # even after cd'ing away. Drone reads this as fallback for caller detection.
    spawn_env["AIPASS_BRANCH_NAME"] = branch_email.lstrip("@")

    # Extract CWD from lock file path (branch_path/.ai_mail.local/.dispatch.lock)
    lock_path = Path(lock_file)
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
    except OSError as e:
        logger.warning("[monitor] Failed to rotate stdout log: %s", e)

    start_time = time.time()

    # ─── Retry Loop: 3 Strikes ─────────────────────────────
    # Strike 1: original command (resume if -c was passed)
    # Strike 2: same command again (transient failure)
    # Strike 3: fresh start (remove -c, abandon potentially corrupted session)
    attempts = []
    exit_code = -1
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

        if stderr_fh is not None:
            stderr_fh.write(f"\n--- Attempt {attempt}/3 ({mode}) at {time.strftime('%H:%M:%S')} ---\n")
            stderr_fh.flush()

        exit_code, startup_failed = _run_with_startup_check(
            cmd, stdout_log, stderr_fh if stderr_fh is not None else subprocess.DEVNULL, cwd, spawn_env, branch_email
        )

        attempts.append({"attempt": attempt, "exit_code": exit_code, "startup_failed": startup_failed, "mode": mode})

        # Success — done
        if exit_code == 0:
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

        # Check stderr for specific error categories
        try:
            with open(stderr_log, "r", encoding="utf-8") as f:
                content = f.read()
            if "rate_limit" in content.lower() or "429" in content:
                reason = f"API rate limit (all {len(attempts)} attempts failed, {duration}s)"
            elif "overloaded" in content.lower() or "529" in content:
                reason = f"API overloaded (all {len(attempts)} attempts failed, {duration}s)"
        except OSError:
            logger.info("[monitor] Failed to read stderr log for diagnostics")

        _send_bounce(branch_email, reason, sender, lock_file, stderr_log)

    # Always clean up lock file — monitor handles this, agent doesn't need to
    try:
        if os.path.exists(lock_file):
            os.unlink(lock_file)
    except OSError:
        logger.info("[monitor] Failed to clean up lock file %s", lock_file)

    # Log completion to Prax
    branch_name = branch_email.lstrip("@")
    status = "completed" if exit_code == 0 else f"FAILED (code {exit_code})"
    if max_turns_hit:
        status = f"MAX TURNS HIT ({duration}s)"
    logger.info("[monitor] @%s %s — %ds", branch_name, status, duration)

    # Desktop notification on completion
    try:
        from aipass.ai_mail.apps.handlers.notify import send_notification

        icon = "dialog-information" if exit_code == 0 else "dialog-warning"
        send_notification(f"@{branch_name} {status}", f"Duration: {duration}s", source=branch_name, icon=icon)
    except Exception:
        logger.info("[monitor] Desktop notification unavailable")

    sys.exit(0 if exit_code == 0 else 1)


if __name__ == "__main__":
    main()
